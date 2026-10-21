"""위젯 배치와 할 일을 화면 설정 JSON의 widgets 항목에 보관한다."""

import json
from copy import deepcopy
from datetime import date, datetime, timezone

from database import Database, DatabaseError, NotFoundError
from settings_store import SettingsStore
from views.counseling_content import clean_html

WIDGET_KINDS = ('clock', 'todo', 'teacher_search', 'meal', 'memo')
DEFAULT_LAYOUT = [{'id': kind, 'kind': kind, 'span': 1} for kind in WIDGET_KINDS[:3]]


class HomeRepository:
    def __init__(self, database: Database, settings: SettingsStore | None = None):
        self.database = database
        self._settings = settings
        self.note_drafts: dict[str, str] = {}

    @property
    def settings(self) -> SettingsStore:
        if self._settings is None:
            self._settings = SettingsStore(self.database.path.parent / 'display-settings.json')
        return self._settings

    def _legacy(self) -> dict:
        """JSON에 위젯 데이터가 없을 때만 이전 DB 데이터를 가져온다."""
        with self.database.session() as connection:
            row = connection.execute('SELECT layout FROM home_preferences WHERE id=1').fetchone()
            todos = [dict(item) for item in connection.execute(
                'SELECT id, title, done FROM home_todos ORDER BY done, id DESC').fetchall()]
        return {'layout': json.loads(row['layout']) if row else deepcopy(DEFAULT_LAYOUT),
                'todos': todos, 'next_todo_id': max((item['id'] for item in todos), default=0) + 1}

    @staticmethod
    def _validate(widgets):
        if not isinstance(widgets, dict):
            raise ValueError('위젯 설정 형식이 올바르지 않습니다.')
        layout, todos = widgets['layout'], widgets['todos']
        if not isinstance(layout, list) or not isinstance(todos, list):
            raise ValueError('위젯 목록 형식이 올바르지 않습니다.')
        widgets['layout'] = HomeRepository.normalize_layout(layout)
        widgets.setdefault('todo_lists', [{'id': 1, 'name': '기본 목록'}])
        widgets.setdefault('selected_todo_list', 1)
        widgets.setdefault('next_todo_list_id', 2)
        lists = widgets['todo_lists']
        if not isinstance(lists, list) or not lists:
            raise ValueError('할 일 목록이 올바르지 않습니다.')
        list_ids = [entry['id'] for entry in lists]
        if (any(type(entry['id']) is not int or entry['id'] < 1
                or not isinstance(entry['name'], str) or not 1 <= len(entry['name'].strip()) <= 60 for entry in lists)
                or len(set(list_ids)) != len(list_ids) or widgets['selected_todo_list'] not in list_ids
                or type(widgets['next_todo_list_id']) is not int or widgets['next_todo_list_id'] <= max(list_ids)):
            raise ValueError('할 일 목록 설정이 올바르지 않습니다.')
        selections = widgets.setdefault('widget_todo_lists', {})
        if not isinstance(selections, dict) or any(not isinstance(key, str) or value not in list_ids
                                                  for key, value in selections.items()):
            raise ValueError('위젯별 할 일 목록 설정이 올바르지 않습니다.')
        notes = widgets.setdefault('notes', {})
        if not isinstance(notes, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                              for key, value in notes.items()):
            raise ValueError('메모 형식이 올바르지 않습니다.')
        ids = []
        for item in todos:
            if (not isinstance(item, dict) or type(item['id']) is not int or item['id'] < 1
                    or not isinstance(item['title'], str) or not 1 <= len(item['title'].strip()) <= 300
                    or item['done'] not in (0, 1)):
                raise ValueError('할 일 형식이 올바르지 않습니다.')
            if item.get('list_id', 1) not in list_ids:
                raise ValueError('할 일 목록을 찾을 수 없습니다.')
            HomeRepository._todo_fields(item['title'], item.get('due_date', ''), item.get('priority', 'normal'))
            ids.append(item['id'])
        if (len(ids) != len(set(ids)) or type(widgets['next_todo_id']) is not int
                or widgets['next_todo_id'] <= max(ids, default=0)):
            raise ValueError('할 일 번호가 올바르지 않습니다.')
        return widgets

    def _update(self, change):
        def update(data):
            if 'widgets' not in data:
                data['widgets'] = self._legacy()
            widgets = self._validate(data['widgets'])
            return change(widgets)
        try:
            return self.settings.update(update)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise DatabaseError('위젯 설정을 저장하지 못했습니다. 설정 파일과 폴더 권한을 확인해 주세요.') from error

    def _read(self) -> dict:
        try:
            data = self.settings.read()
            if 'widgets' in data:
                return self._validate(data['widgets'])
            return self._update(lambda widgets: widgets)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise DatabaseError('위젯 설정을 읽지 못했습니다. 설정 파일을 확인해 주세요.') from error

    def layout(self) -> list[dict]:
        return self._read()['layout']

    @staticmethod
    def normalize_layout(layout: list[dict]) -> list[dict]:
        """이전 종류별 배치에는 결정적인 ID를 부여해 선택 상태를 유지한다."""
        normalized = [deepcopy(item) for item in layout]
        ids = set()
        for index, item in enumerate(normalized):
            if not isinstance(item, dict) or item.get('kind') not in WIDGET_KINDS:
                raise ValueError('지원하지 않는 위젯입니다.')
            if item.get('span') not in (1, 2, 3):
                raise ValueError('위젯 너비는 1~3열이어야 합니다.')
            if type(item.get('height', 290)) is not int or not 290 <= item.get('height', 290) <= 900:
                raise ValueError('위젯 높이는 290~900px이어야 합니다.')
            if 'id' not in item:
                item['id'] = item['kind'] if item['kind'] not in ids else f"{item['kind']}-{index}"
            instance_id = item['id']
            if (not isinstance(instance_id, str) or not instance_id
                    or any(not (char.isascii() and (char.isalnum() or char in '-_')) for char in instance_id)
                    or instance_id in ids):
                raise ValueError('위젯 ID가 올바르지 않거나 중복되었습니다.')
            ids.add(instance_id)
        return normalized

    def save_layout(self, layout: list[dict]) -> None:
        layout = self.normalize_layout(layout)
        self._update(lambda widgets: widgets.update(layout=layout))

    def note(self, instance_id: str) -> str:
        if instance_id in self.note_drafts:
            return clean_html(self.note_drafts[instance_id])
        return clean_html(self._read()['notes'].get(instance_id, ''))

    def save_note(self, instance_id: str, content: str) -> None:
        if not isinstance(content, str) or len(content) > 100_000:
            raise ValueError('메모는 서식을 포함해 100,000자까지 저장할 수 있습니다.')
        content = clean_html(content)
        self._update(lambda widgets: widgets['notes'].update({instance_id: content}))
        self.note_drafts.pop(instance_id, None)

    @staticmethod
    def _todo_fields(title, due_date, priority):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 300:
            raise ValueError('할 일을 1~300자로 입력해 주세요.')
        if priority not in ('high', 'normal', 'low'):
            raise ValueError('우선순위를 확인해 주세요.')
        if not isinstance(due_date, str):
            raise ValueError('기한을 확인해 주세요.')
        if due_date:
            try:
                if date.fromisoformat(due_date).isoformat() != due_date:
                    raise ValueError
            except ValueError:
                raise ValueError('기한을 YYYY-MM-DD 형식으로 입력해 주세요.') from None

    def todo_state(self, instance_id: str | None = None) -> dict:
        widgets = self._read()
        state = {key: widgets[key] for key in ('todo_lists', 'selected_todo_list', 'todos')}
        if instance_id is not None:
            state['selected_todo_list'] = widgets['widget_todo_lists'].get(instance_id, widgets['selected_todo_list'])
        return state

    def add_todo_list(self, name: str, instance_id: str | None = None) -> None:
        name = name.strip()
        if not 1 <= len(name) <= 60:
            raise ValueError('목록 이름을 1~60자로 입력해 주세요.')
        # 같은 이름 생성은 UI에서 구별하기 어려우므로 거부한다.
        def add(widgets):
            if any(entry['name'] == name for entry in widgets['todo_lists']):
                raise NotFoundError('같은 이름의 목록이 이미 있습니다.')
            list_id = widgets['next_todo_list_id']
            widgets['todo_lists'].append({'id': list_id, 'name': name})
            widgets['next_todo_list_id'] += 1
            if instance_id is None:
                widgets['selected_todo_list'] = list_id
            else:
                widgets['widget_todo_lists'][instance_id] = list_id
        self._update(add)

    def select_todo_list(self, list_id: int, instance_id: str | None = None) -> None:
        def select(widgets):
            if not any(entry['id'] == list_id for entry in widgets['todo_lists']):
                raise NotFoundError('목록을 찾을 수 없습니다.')
            if instance_id is None:
                widgets['selected_todo_list'] = list_id
            else:
                widgets['widget_todo_lists'][instance_id] = list_id
        self._update(select)

    def todos(self) -> list[dict]:
        return sorted(self._read()['todos'], key=lambda item: (item['done'], -item['id']))

    def add_todo(self, title: str, list_id: int | None = None,
                 due_date: str = '', priority: str = 'normal') -> None:
        self._todo_fields(title, due_date, priority)
        def add(widgets):
            target = list_id if list_id is not None else widgets['selected_todo_list']
            if not any(entry['id'] == target for entry in widgets['todo_lists']):
                raise NotFoundError('목록을 찾을 수 없습니다.')
            todo_id = widgets['next_todo_id']
            widgets['todos'].append({'id': todo_id, 'title': title.strip(), 'done': 0,
                                     'list_id': target, 'due_date': due_date, 'priority': priority})
            widgets['next_todo_id'] += 1
        self._update(add)

    def edit_todo(self, todo_id: int, title: str, due_date: str, priority: str) -> None:
        self._todo_fields(title, due_date, priority)
        def edit(widgets):
            for item in widgets['todos']:
                if item['id'] == todo_id:
                    item.update(title=title.strip(), due_date=due_date, priority=priority)
                    return
            raise NotFoundError('할 일을 찾을 수 없습니다.')
        self._update(edit)

    def complete_todo(self, todo_id: int, done: bool) -> None:
        def complete(widgets):
            for item in widgets['todos']:
                if item['id'] == todo_id:
                    item['done'] = int(done)
                    item['completed_at'] = datetime.now(timezone.utc).isoformat() if done else ''
                    return
            raise NotFoundError('할 일을 찾을 수 없습니다.')
        self._update(complete)

    def delete_todo(self, todo_id: int) -> None:
        def delete(widgets):
            widgets['todos'] = [item for item in widgets['todos'] if item['id'] != todo_id]
        self._update(delete)
