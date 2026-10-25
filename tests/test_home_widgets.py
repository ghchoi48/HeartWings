"""홈 저장소의 지속성, 마이그레이션, 검색 범위와 배치 실패 복원 검증."""

import asyncio
import inspect
import json
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.core.models import (TeacherInput, StudentInput, CounselingInput, GroupCounselingInput,
                                   GroupLogInput, ConsultationInput, SpecialEducationInput)
from maeumnarae.repositories.home_repo import DEFAULT_LAYOUT, HomeRepository, WIDGET_KINDS
from maeumnarae.repositories.teacher_repo import TeacherRepository
from maeumnarae.views.home_view import HomeView
from maeumnarae.views.display_settings import DisplaySettings
from maeumnarae.core.settings_store import SettingsStore
from maeumnarae.views.home_layout import arrange, overlaps, DEFAULT_SIZES
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.repositories.counseling_repo import CounselingRepository
from maeumnarae.repositories.group_counseling_repo import GroupCounselingRepository
from maeumnarae.repositories.consultation_repo import ConsultationRepository
from maeumnarae.repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from maeumnarae.services.school_timetable import normalize_timetable
from maeumnarae.widgets import WIDGETS
from maeumnarae.widgets.scheduled_journals import ScheduledJournals
from maeumnarae.widgets.school_timetable import SchoolTimetable, active_period, KST


def test_reinitialize_and_home_persistence(tmp_path):
    path = tmp_path / 'home.db'
    db = Database('test-password', path)
    db.initialize()
    teachers = TeacherRepository(db)
    teachers.save(TeacherInput(name='기존 교사'))
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
        connection.execute('INSERT INTO home_preferences (id, layout) VALUES (1, ?)', (json.dumps(layout),))
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
    with patch('maeumnarae.views.display_settings.ui.run_javascript'):
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
    with patch('maeumnarae.core.settings_store.Path.replace', side_effect=OSError('read-only')):
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
            repo.widget_sizes.return_value = {'clock': {'width': 8, 'height': 290}}
            teachers = Mock()
            view = HomeView(repo, teachers, Mock())
            host = ui.column()

            async def invoke(fn, *args, **kwargs):
                return fn(*args, **kwargs)

            with host, patch('maeumnarae.views.home_view.ui.timer'), patch('maeumnarae.views.home_view.run.io_bound', side_effect=invoke):
                view.build()
                await view.load()
                view.toggle_edit()
                await view.change_geometry('todo', {'width': 11, 'height': 430, 'x': 3, 'y': 40})
                todo = next(item for item in view.layout if item['id'] == 'todo')
                assert (todo['width'], todo['height'], todo['x'], todo['y']) == (11, 430, 3, 40)
                await view.change_geometry('todo', {'width': 25, 'height': 1})
                assert next(item for item in view.layout if item['id'] == 'todo') == todo
                await view.change_geometry('todo', {'x': 19})
                assert next(item for item in view.layout if item['id'] == 'todo')['x'] == 13
                await view.change_geometry('clock', {'x': 13, 'y': 40})
                assert not any(overlaps(a, b) for i, a in enumerate(view.layout) for b in view.layout[i+1:])
                await view.remove(1)
                assert [item['kind'] for item in view.layout] == ['clock', 'todo']
                saved = [dict(item) for item in view.layout]
                repo.save_layout.side_effect = DatabaseError('저장 실패')
                with patch('maeumnarae.views.home_view.ui.notify') as notify:
                    await view.change_geometry('clock', {'width': 24, 'height': 500})
                assert view.layout == saved
                notify.assert_called_once()
            host.delete()



    async def test_edit_mode_keeps_contents_and_header_settings(self):
        with Client(page('/home-edit-contents')), patch('maeumnarae.views.home_view.ui.timer'):
            view = HomeView(Mock(), Mock(), Mock())
            view.build()
            view.layout = arrange([
                dict(id=kind, kind=kind, width=8, height=400)
                for kind in ('scheduled_journals', 'weather', 'school_timetable')
            ])
            view.editing = True
            view.render()
            assert len(view.widget_views) == 3
            assert all(not widget.body.is_deleted for widget in view.widget_views)
            cards = [element for element in view.grid.descendants() if 'home-widget' in element.classes]
            for card in cards:
                header = next(iter(card))
                buttons = [element for element in header.descendants() if isinstance(element, ui.button)]
                expected = ['delete_outline']
                if card.props['data-kind'] != 'scheduled_journals':
                    expected.append('edit')
                assert [button.props['icon'] for button in buttons] == expected
            view.editing = False
            view.render()
            assert len(view.widget_views) == 3
            assert not any(isinstance(element, ui.button) and
                           element.props.get('icon') in ('edit', 'delete_outline')
                           for element in view.grid.descendants())


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


def test_fine_layout_migration_and_collision_resolution():
    legacy = [{'id': str(i), 'kind': 'clock', 'span': 1} for i in range(3)]
    positioned = arrange(legacy)
    assert [(item['x'], item['y'], item['width']) for item in positioned] == [(0, 0, 8), (8, 0, 8), (16, 0, 8)]
    assert 'x' not in legacy[0]
    positioned[1].update(x=0, y=0, width=13, height=170)
    moved = arrange(positioned, priority='1')
    assert moved[1]['x'] == moved[1]['y'] == 0
    assert not any(overlaps(a, b) for i, a in enumerate(moved) for b in moved[i+1:])
    assert arrange(moved) == moved
    assert arrange([]) == []


def test_fine_layout_and_default_sizes_persist(tmp_path):
    db = Database('test-password', tmp_path / 'fine.db')
    db.initialize()
    repo = HomeRepository(db)
    layout = [{'id': 'memo-a', 'kind': 'memo', 'width': 7, 'height': 180, 'x': 13, 'y': 45}]
    repo.save_layout(layout)
    repo.save_widget_size('memo', 11, 610)
    reopened = HomeRepository(db)
    assert reopened.layout() == layout
    assert reopened.widget_sizes()['memo'] == {'width': 11, 'height': 610}
    assert reopened.widget_sizes()['meal']['height'] == 520
    for changes in ({'width': 25}, {'width': True}, {'height': 159}, {'height': 1601},
                    {'x': -1}, {'x': 20}, {'y': -1}, {'y': 0.5}):
        with pytest.raises(ValueError):
            repo.save_layout([{**layout[0], **changes}])
    assert reopened.layout() == layout
    with pytest.raises(ValueError):
        repo.save_widget_size('memo', 0, 200)
    assert reopened.widget_sizes()['memo']['width'] == 11


def test_square_grid_conversion_is_stable():
    old = [{'id': 'a', 'kind': 'clock', 'width': 8, 'height': 290, 'x': 0, 'y': 40},
           {'id': 'b', 'kind': 'memo', 'width': 8, 'height': 430, 'x': 0, 'y': 70}]
    converted = arrange(old)
    assert converted[0]['y'] == 10
    assert all(item['grid'] == 'square' for item in converted)
    assert not overlaps(*converted)
    assert arrange(converted) == converted
    assert 'grid' not in old[0]


def test_widget_addition_only_while_editing():
    with Client(page('/home-edit-controls')), patch('maeumnarae.views.home_view.ui.timer'):
        view = HomeView(Mock(), Mock(), Mock())
        view.build()
        view.loaded = True
        view.render()
        assert not view.add_button.visible
        with patch('maeumnarae.views.home_view.ui.dialog') as dialog:
            view.open_picker()
            dialog.assert_not_called()
        view.toggle_edit()
        assert view.add_button.visible and view.add_button.enabled
        view.layout = arrange([{'id': 'clock', 'kind': 'clock', 'width': 8, 'height': 290}])
        view.render()
        assert not any(isinstance(element, ui.number) for element in view.grid.descendants())
        view.open_picker()
        dialogs = [e for e in ui.context.client.elements.values() if isinstance(e, ui.dialog)]
        assert len(dialogs) == 1
        assert not any(isinstance(e, ui.number) for e in dialogs[0].descendants())
        view.toggle_edit()
        assert not view.add_button.visible


SCHEDULE = [dict(label='1교시', start='09:00', end='09:50'),
            dict(label='2교시', start='10:00', end='10:50')]


@pytest.fixture
def home(tmp_path):
    db = Database('test-only', tmp_path / 'home.db')
    db.initialize()
    return HomeRepository(db)


async def inline(function, *args, **kwargs):
    return function(*args, **kwargs)


def test_scheduled_counts_through_today_and_status_changes(home):
    db = home.database
    assert home.scheduled_journal_counts() == {'개인상담': 0, '집단상담': 0, '자문': 0, '특별교육': 0}
    student = StudentRepository(db).create(StudentInput(name='테스트 학생', grade=1, classroom='1'))
    teacher = TeacherRepository(db).save(TeacherInput(name='테스트 교사'))
    group_repo = GroupCounselingRepository(db)
    group = group_repo.save(GroupCounselingInput(name='집단'))
    special = SpecialEducationRepository(db).save(SpecialEducationInput(student_id=student.id, title='교육', law='교원지위법'))
    for starts_at, status in [
        (datetime(2020, 1, 1, tzinfo=KST), 'scheduled'),
        (datetime(2026, 10, 25, 23, 59, 59, 999999, tzinfo=KST), 'scheduled'),
        (datetime(2026, 10, 26, tzinfo=KST), 'scheduled'),
        (datetime(2030, 1, 1, tzinfo=KST), 'scheduled'),
        (datetime(2026, 1, 1, tzinfo=KST), 'completed'),
        (datetime(2026, 1, 1, tzinfo=KST), 'cancelled'),
    ]:
        common = dict(title='제목', starts_at=starts_at, status=status)
        CounselingRepository(db).create(CounselingInput(student_id=student.id, **common))
        group_repo.save_log(GroupLogInput(group_id=group.id, **common))
        ConsultationRepository(db).save(ConsultationInput(teacher_id=teacher.id, **common))
        SpecialEducationLogRepository(db).create(CounselingInput(student_id=student.id, case_id=special.id, **common))
    with patch('maeumnarae.repositories.home_repo.datetime') as clock:
        # UTC 날짜는 전날이지만 한국 시각으로는 25일이며, 오늘 늦은 예약도 포함한다.
        clock.now.return_value = datetime(2026, 10, 25, 0, 30, tzinfo=KST)
        assert home.scheduled_journal_counts() == {'개인상담': 2, '집단상담': 2, '자문': 2, '특별교육': 2}
    with db.session(write=True) as connection:
        connection.execute("UPDATE counseling SET status='completed' WHERE status='scheduled'")
    assert home.scheduled_journal_counts()['개인상담'] == 0


def test_widget_registration_and_timetable_persistence(home):
    assert set(WIDGETS) == set(WIDGET_KINDS) == set(DEFAULT_SIZES)
    home.save_layout([dict(id=kind, kind=kind, width=8, height=400)
                      for kind in ('scheduled_journals', 'school_timetable')])
    assert home.school_timetable() == []
    home.save_school_timetable(list(reversed(SCHEDULE)))
    reopened = HomeRepository(home.database)
    assert reopened.school_timetable() == SCHEDULE
    assert len(reopened.layout()) == 2
    with pytest.raises(ValueError, match='겹칩니다'):
        home.save_school_timetable([SCHEDULE[0], dict(label='겹치는 교시', start='09:30', end='10:30')])
    assert reopened.school_timetable() == SCHEDULE
    home.save_school_timetable([])
    assert reopened.school_timetable() == []


@pytest.mark.parametrize('row', [
    dict(label='', start='09:00', end='10:00'),
    dict(label='교시', start='', end='10:00'),
    dict(label='교시', start='24:00', end='25:00'),
    dict(label='교시', start='10:00', end='09:00'),
    dict(label='교시', start='10:00', end='10:00'),
])
def test_timetable_rejects_invalid_rows(row):
    with pytest.raises(ValueError):
        normalize_timetable([row])


def test_active_period_uses_korean_time_and_excludes_end():
    assert active_period(SCHEDULE, datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)) == SCHEDULE[0]
    assert active_period(SCHEDULE, datetime(2026, 10, 26, 9, 49, 59, tzinfo=KST)) == SCHEDULE[0]
    assert active_period(SCHEDULE, datetime(2026, 10, 26, 9, 50, tzinfo=KST)) is None
    assert active_period(SCHEDULE, datetime(2026, 10, 26, 10, 0, tzinfo=KST)) == SCHEDULE[1]
    assert active_period([], datetime.now(KST)) is None
    assert normalize_timetable([SCHEDULE[0], dict(label='연속 활동', start='09:50', end='10:00')])


def test_scheduled_widget_refresh_error_and_recovery():
    async def check():
        home = Mock()
        home.scheduled_journal_counts.return_value = {'개인상담': 2, '집단상담': 1, '자문': 0, '특별교육': 3}
        with Client(page('/scheduled-widget')), patch('maeumnarae.widgets.scheduled_journals.ui.timer'), \
                patch('maeumnarae.widgets.scheduled_journals.run.io_bound', side_effect=inline):
            widget = ScheduledJournals(home, None)
            widget.build()
            await widget.reload()
            labels = [e.text for e in widget.body.descendants() if isinstance(e, ui.label)]
            assert '6' in labels and '3건' in labels
            home.scheduled_journal_counts.side_effect = DatabaseError('집계 실패')
            await widget.reload()
            assert '집계 실패' in [e.text for e in widget.body.descendants() if isinstance(e, ui.label)]
            assert widget.refresh.enabled and not widget.busy
            home.scheduled_journal_counts.side_effect = None
            home.scheduled_journal_counts.return_value = dict.fromkeys(['개인상담', '집단상담', '자문', '특별교육'], 0)
            await widget.reload()
            assert '미작성 일지가 없습니다.' in [e.text for e in widget.body.descendants() if isinstance(e, ui.label)]
    asyncio.run(check())


def test_timetable_editor_validates_preserves_input_and_saves(home):
    async def check():
        with Client(page('/timetable-editor')), patch('maeumnarae.widgets.school_timetable.ui.timer'), \
                patch('maeumnarae.widgets.school_timetable.run.io_bound', side_effect=inline):
            widget = SchoolTimetable(home, None)
            widget.build()
            await widget.reload()

            async def interact(dialog):
                fields = {e.label: e for e in dialog.descendants() if isinstance(e, (ui.input, ui.time_input))}
                fields['교시/활동'].value = '1교시'
                fields['시작 시각'].value = '오전 09:00'
                fields['종료 시각'].value = '오전 08:00'
                button = next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == '저장')
                handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
                save = inspect.getclosurevars(handler).nonlocals['callback']
                await save()
                assert not dialog.submitted.is_set()
                assert fields['교시/활동'].value == '1교시' and button.enabled
                assert home.school_timetable() == []
                fields['종료 시각'].value = '오전 09:50'
                with patch.object(home, 'save_school_timetable', side_effect=DatabaseError('저장 실패')):
                    await save()
                assert not dialog.submitted.is_set() and button.enabled
                await save()
                return dialog._result

            with patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()):
                await widget.open_settings()
            assert home.school_timetable() == [SCHEDULE[0]]
            assert widget.rows == [SCHEDULE[0]] and not widget.editing
    asyncio.run(check())
