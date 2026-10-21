"""홈 저장소의 지속성, 마이그레이션, 검색 범위와 배치 실패 복원 검증."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from database import Database, DatabaseError
from models import TeacherInput
from repositories.home_repo import DEFAULT_LAYOUT, HomeRepository
from repositories.teacher_repo import TeacherRepository
from views.home_view import HomeView
from views.display_settings import DisplaySettings
from settings_store import SettingsStore


def test_migration_and_home_persistence(tmp_path):
    path = tmp_path / 'home.db'
    db = Database('test-password', path)
    db.initialize()
    teachers = TeacherRepository(db)
    teachers.save(TeacherInput(name='기존 교사'))
    with db.session(write=True) as connection:
        connection.execute('DROP TABLE home_preferences')
        connection.execute('DROP TABLE home_todos')
        connection.execute('PRAGMA user_version=24')
    db.initialize()
    repo = HomeRepository(db)
    assert repo.layout() == DEFAULT_LAYOUT
    repo.add_todo('  상담 준비  ')
    todo = repo.todos()[0]
    repo.complete_todo(todo['id'], True)
    layout = [{'kind': 'todo', 'span': 2, 'height': 430}, {'kind': 'clock', 'span': 1}]
    repo.save_layout(layout)
    reopened = Database('test-password', path)
    reopened.initialize()
    saved = HomeRepository(reopened)
    assert saved.layout() == HomeRepository.normalize_layout(layout)
    saved_todo = saved.todos()[0]
    assert saved_todo['id'] == todo['id']
    assert saved_todo['title'] == '상담 준비'
    assert saved_todo['done'] == 1
    assert saved_todo['completed_at']
    saved.save_layout([])
    assert saved.layout() == []
    assert len(saved.todos()) == 1
    saved.delete_todo(todo['id'])
    assert saved.todos() == []
    assert TeacherRepository(reopened).list()[0].name == '기존 교사'
    with pytest.raises(ValueError):
        saved.add_todo(' ')
    with pytest.raises(ValueError):
        saved.save_layout([{'kind': 'clock', 'span': 4}])
    with pytest.raises(ValueError):
        saved.save_layout([{'id': 'same', 'kind': 'clock', 'span': 1}] * 2)
    with pytest.raises(ValueError):
        saved.save_layout([{'kind': 'clock', 'span': 1, 'height': 10000}])


def test_legacy_data_moves_to_shared_json_only_once(tmp_path):
    db = Database('test-password', tmp_path / 'legacy.db')
    db.initialize()
    layout = [{'kind': 'todo', 'span': 3}]
    with db.session(write=True) as connection:
        connection.execute('INSERT INTO home_preferences VALUES (1, ?)', (json.dumps(layout),))
        connection.execute("INSERT INTO home_todos (id, title, done) VALUES (7, '기존 할 일', 1)")
    path = tmp_path / 'display-settings.json'
    path.write_text(json.dumps({'mode': 'dark', 'size': 18, 'font': 'system', 'other': 123}))
    first_display = DisplaySettings(path)
    second_display = DisplaySettings(path)
    repo = HomeRepository(db, first_display.store)
    assert repo.layout() == HomeRepository.normalize_layout(layout)
    assert repo.todos() == [{'id': 7, 'title': '기존 할 일', 'done': 1}]
    repo.add_todo('새 할 일')
    second_display.change('mode', 'light')
    with patch('views.display_settings.ui.run_javascript'):
        first_display.change('size', 20)
    data = json.loads(path.read_text())
    assert data['mode'] == 'light'
    assert data['size'] == 20
    assert data['other'] == 123
    assert len(data['widgets']['todos']) == 2
    assert data['widgets']['next_todo_id'] == 9
    repo.save_layout([])
    repo.delete_todo(7)
    repo.delete_todo(8)
    reopened = HomeRepository(db, SettingsStore(path))
    assert reopened.layout() == []
    assert reopened.todos() == []  # 이전 DB 데이터가 다시 나타나지 않는다.
    with db.session() as connection:
        assert connection.execute('SELECT COUNT(*) FROM home_todos').fetchone()[0] == 1
        assert json.loads(connection.execute('SELECT layout FROM home_preferences').fetchone()[0]) == layout


def test_failed_json_save_preserves_previous_data(tmp_path):
    db = Database('test-password', tmp_path / 'home.db')
    db.initialize()
    repo = HomeRepository(db)
    repo.add_todo('유지할 할 일')
    path = tmp_path / 'display-settings.json'
    before = path.read_bytes()
    with patch('settings_store.Path.replace', side_effect=OSError('read-only')):
        with pytest.raises(DatabaseError):
            repo.add_todo('실패할 할 일')
    assert path.read_bytes() == before
    assert len(repo.todos()) == 1
    assert not list(tmp_path.glob('*.tmp'))
    path.write_text('broken json')
    with pytest.raises(DatabaseError):
        repo.save_layout([])
    assert path.read_text() == 'broken json'
    path.write_text(json.dumps({'widgets': {}}))
    with pytest.raises(DatabaseError):
        repo.layout()


def test_teacher_search_uses_full_directory_and_literal_patterns(tmp_path):
    db = Database('test-password', tmp_path / 'search.db')
    db.initialize()
    repo = TeacherRepository(db)
    for index in range(105):
        repo.save(TeacherInput(name=f'교사{index:03}'))
    target = repo.save(TeacherInput(name='홍길동', responsibilities='상담 100%_담당'))
    assert repo.search('홍길동') == [target]
    assert repo.search('상담') == [target]
    assert repo.search('%_') == [target]
    assert len(repo.search('')) == 50


class HomeViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_layout_moves_resizes_removes_and_restores_failed_save(self):
        with Client(page('/home-test')):
            repo = Mock()
            repo.layout.return_value = [dict(item) for item in DEFAULT_LAYOUT]
            teachers = Mock()
            view = HomeView(repo, teachers, Mock())
            host = ui.column()

            async def invoke(fn, *args, **kwargs):
                return fn(*args, **kwargs)

            with host, patch('views.home_view.ui.timer'), patch('views.home_view.run.io_bound', side_effect=invoke):
                view.build()
                await view.load()
                view.toggle_edit()
                await view.drop(SimpleNamespace(old_index=0, new_index=2))
                assert view.layout[-1]['kind'] == 'clock'
                await view.resize_drag('todo', {'span': 2, 'height': 430})
                assert view.layout[0] == {'id': 'todo', 'kind': 'todo', 'span': 2, 'height': 430}
                await view.resize_drag('todo', {'span': 9, 'height': 1})
                assert view.layout[0]['height'] == 430
                await view.drop(SimpleNamespace(old_index=2, new_index=0))
                await view.move(0, 1)
                assert view.layout[0]['kind'] == 'todo'
                await view.resize(0, 2)
                assert view.layout[0]['span'] == 2
                await view.remove(0)
                assert [item['kind'] for item in view.layout] == ['clock', 'teacher_search']
                repo.save_layout.side_effect = DatabaseError('저장 실패')
                with patch('views.home_view.ui.notify') as notify:
                    await view.resize_drag('clock', {'span': 3, 'height': 500})
                assert view.layout[0] == {'id': 'clock', 'kind': 'clock', 'span': 1}
                assert len(view.layout) == 2
                notify.assert_called_once()
            host.delete()


def test_multiple_todo_lists_due_priority_and_completion(tmp_path):
    db = Database('test-password', tmp_path / 'lists.db')
    db.initialize()
    repo = HomeRepository(db)
    repo.add_todo('기본 할 일')
    repo.add_todo_list('상담 준비')
    state = repo.todo_state()
    list_id = state['selected_todo_list']
    assert list_id != 1
    repo.add_todo('검사 준비', list_id, '2026-11-01', 'high')
    item = next(item for item in repo.todos() if item['list_id'] == list_id)
    repo.edit_todo(item['id'], '검사지 인쇄', '2026-11-02', 'low')
    repo.complete_todo(item['id'], True)
    reopened = HomeRepository(db)
    state = reopened.todo_state()
    assert state['selected_todo_list'] == list_id
    edited = next(entry for entry in state['todos'] if entry['id'] == item['id'])
    assert (edited['title'], edited['due_date'], edited['priority']) == ('검사지 인쇄', '2026-11-02', 'low')
    assert edited['completed_at']
    repo.complete_todo(edited['id'], False)
    assert next(item for item in repo.todos() if item['id'] == edited['id'])['completed_at'] == ''
    repo.select_todo_list(1)
    assert repo.todo_state()['selected_todo_list'] == 1
    with pytest.raises(DatabaseError):
        repo.add_todo_list('상담 준비')
    with pytest.raises(ValueError):
        repo.add_todo('잘못된 기한', 1, '2026-02-30')
    with pytest.raises(ValueError):
        repo.edit_todo(edited['id'], '잘못된 순위', '', 'unknown')
    with pytest.raises(DatabaseError):
        repo.select_todo_list(999)


def test_duplicate_widgets_keep_ids_and_independent_selections(tmp_path):
    db = Database('test-password', tmp_path / 'duplicates.db')
    db.initialize()
    repo = HomeRepository(db)
    layout = [{'id': 'todo-a', 'kind': 'todo', 'span': 1},
              {'id': 'todo-b', 'kind': 'todo', 'span': 2, 'height': 500}]
    repo.save_layout(layout)
    repo.add_todo_list('업무', 'todo-b')
    second_list = repo.todo_state('todo-b')['selected_todo_list']
    assert repo.todo_state('todo-a')['selected_todo_list'] == 1
    repo.add_todo('업무 할 일', second_list)
    repo.save_layout(list(reversed(layout)))
    reopened = HomeRepository(db)
    assert reopened.layout() == list(reversed(layout))
    assert reopened.todo_state('todo-b')['selected_todo_list'] == second_list
    assert reopened.todo_state('todo-a')['selected_todo_list'] == 1
    repo.save_layout([layout[0]])
    assert repo.layout() == [layout[0]]
    assert len(repo.todos()) == 1
    repo.select_todo_list(second_list, 'todo-a')
    assert repo.todo_state('todo-a')['todos'] == repo.todo_state('todo-b')['todos']


def test_old_layout_gets_stable_ids_without_losing_settings(tmp_path):
    db = Database('test-password', tmp_path / 'old.db')
    db.initialize()
    store = SettingsStore(tmp_path / 'display-settings.json')
    store.update(lambda data: data.update(widgets={
        'layout': [{'kind': 'todo', 'span': 2, 'height': 440}],
        'todos': [], 'next_todo_id': 1,
        'todo_lists': [{'id': 1, 'name': '기본'}, {'id': 2, 'name': '기존 선택'}],
        'selected_todo_list': 2, 'next_todo_list_id': 3}))
    repo = HomeRepository(db, store)
    first = repo.layout()[0]
    assert first == {'id': 'todo', 'kind': 'todo', 'span': 2, 'height': 440}
    assert repo.layout()[0] == first
    assert repo.todo_state(first['id'])['selected_todo_list'] == 2
