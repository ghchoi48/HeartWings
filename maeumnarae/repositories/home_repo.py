"""위젯 데이터와 메모·할 일을 현재 암호화 DB에 보관한다."""

import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

from maeumnarae.core.database import Database, DatabaseError, NotFoundError
from maeumnarae.core.settings_store import SettingsStore
from maeumnarae.views.home_layout import COLUMNS, MIN_HEIGHT, MAX_HEIGHT, DEFAULT_SIZES, GRID_VERSION, arrange
from maeumnarae.views.counseling_content import clean_html
from maeumnarae.services.school_timetable import normalize_timetable
from maeumnarae.repositories._support import utc_text

WIDGET_KINDS = ('clock', 'todo', 'teacher_search', 'meal', 'memo', 'weather', 'scheduled_journals', 'school_timetable', 'calendar')
DEFAULT_LAYOUT = [{'id': kind, 'kind': kind, 'span': 1} for kind in ('clock', 'meal', 'todo')]


class HomeRepository:
    def __init__(self, database: Database, settings: SettingsStore | None = None):
        self.database = database
        self._settings = settings
        self.note_drafts: dict[str, str] = {}
        self._storage_ready = False

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

    def _ensure_storage(self) -> None:
        if self._storage_ready:
            return
        # 이전 JSON에는 DB 식별자가 없으므로 처음 여는 DB가 한 번만 인수한다.
        # 인수 대상을 먼저 기록하여 DB 커밋/JSON 정리 사이에 중단되어도 다른 DB로 복제하지 않는다.
        with self.database._session_lock, self.settings.locked():
            with self.database.session() as connection:
                exists = connection.execute('SELECT 1 FROM home_widget_state WHERE id=1').fetchone()
            data = self.settings.read()
            owner = str(self.database.path.resolve())
            legacy = data.get('widgets')
            eligible = legacy is not None and data.get('widgets_migration_owner', owner) == owner
            if not exists:
                widgets = self._validate(deepcopy(legacy) if eligible else self._legacy())
                if eligible:
                    self.settings.update(lambda settings: settings.update(widgets_migration_owner=owner))
                with self.database.session(write=True) as connection:
                    connection.execute('INSERT INTO home_widget_state (id, payload) VALUES (1, ?)',
                                       (json.dumps(widgets, ensure_ascii=False),))
            if eligible:
                def remove_plaintext(settings):
                    settings.pop('widgets', None)
                    settings.pop('widgets_migration_owner', None)
                self.settings.update(remove_plaintext)
            self._storage_ready = True

    def _update(self, change):
        try:
            self._ensure_storage()
            with self.database.session(write=True) as connection:
                widgets = self._validate(json.loads(connection.execute(
                    'SELECT payload FROM home_widget_state WHERE id=1').fetchone()[0]))
                result = change(widgets)
                connection.execute('UPDATE home_widget_state SET payload=? WHERE id=1',
                                   (json.dumps(widgets, ensure_ascii=False),))
                return deepcopy(result)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise DatabaseError('위젯 데이터를 저장하지 못했습니다. DB와 설정 파일을 확인해 주세요.') from error

    def _read(self) -> dict:
        try:
            self._ensure_storage()
            with self.database.session() as connection:
                return self._validate(json.loads(connection.execute(
                    'SELECT payload FROM home_widget_state WHERE id=1').fetchone()[0]))
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise DatabaseError('위젯 데이터를 읽지 못했습니다. DB와 설정 파일을 확인해 주세요.') from error

    def layout(self) -> list[dict]:
        return self._read()['layout']

    def scheduled_journal_counts(self):
        """한국 시각 오늘까지의 예약 일지만 집계하며 제목·본문 등은 읽지 않는다."""
        tomorrow = datetime.now(timezone(timedelta(hours=9))).replace(
            hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        with self.database.session() as connection:
            return dict(connection.execute('''
                SELECT '개인상담', count(*) FROM counseling WHERE status='scheduled' AND starts_at < :end
                UNION ALL SELECT '집단상담', count(*) FROM group_counseling_logs WHERE status='scheduled' AND starts_at < :end
                UNION ALL SELECT '자문', count(*) FROM consultations WHERE status='scheduled' AND starts_at < :end
                UNION ALL SELECT '특별교육', count(*) FROM special_education_logs WHERE status='scheduled' AND starts_at < :end
            ''', {'end': utc_text(tomorrow)}).fetchall())

    def school_timetable(self):
        return normalize_timetable(self._read().get('school_timetable', []))

    def save_school_timetable(self, rows):
        normalized = normalize_timetable(rows)
        self._update(lambda widgets: widgets.update(school_timetable=normalized))

    @staticmethod
    def normalize_layout(layout: list[dict]) -> list[dict]:
        """이전 종류별 배치에는 결정적인 ID를 부여해 선택 상태를 유지한다."""
        normalized = [deepcopy(item) for item in layout]
        ids = set()
        for index, item in enumerate(normalized):
            if not isinstance(item, dict) or item.get('kind') not in WIDGET_KINDS:
                raise ValueError('지원하지 않는 위젯입니다.')
            if 'width' not in item and item.get('span') not in (1, 2, 3):
                raise ValueError('위젯 너비는 1~3열이어야 합니다.')
            columns = COLUMNS if item.get('grid') == GRID_VERSION else 24
            if type(item.get('height', 290)) is not int or not MIN_HEIGHT <= item.get('height', 290) <= MAX_HEIGHT:
                raise ValueError('위젯 높이는 160~1600px이어야 합니다.')
            if 'width' in item and (type(item['width']) is not int or not 1 <= item['width'] <= columns):
                raise ValueError(f'위젯 너비는 1~{columns}칸이어야 합니다.')
            if ('x' in item) != ('y' in item):
                raise ValueError('위젯의 가로·세로 위치를 함께 지정해 주세요.')
            if 'x' in item and (type(item['x']) is not int or type(item['y']) is not int
                                or not 0 <= item['x'] <= columns - item.get('width', item.get('span', 1) * 8)
                                or item['y'] < 0):
                raise ValueError('위젯 위치가 격자 범위를 벗어났습니다.')
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

    def widget_sizes(self):
        sizes = {kind: {'width': width, 'height': height} for kind, (width, height) in DEFAULT_SIZES.items()}
        for kind, size in self._read().get('default_sizes', {}).items():
            self.normalize_layout([{'kind': kind, **size}])
            converted = arrange([{'id': kind, 'kind': kind, **size}])[0]
            sizes[kind] = {key: converted[key] for key in ('width', 'height')}
        for kind, size in sizes.items():
            self.normalize_layout([{'kind': kind, **size, 'grid': GRID_VERSION}])
        return sizes

    def save_widget_size(self, kind, width, height):
        self.normalize_layout([{'kind': kind, 'width': width, 'height': height, 'grid': GRID_VERSION}])
        self._update(lambda widgets: widgets.setdefault('default_sizes', {}).update(
            {kind: {'width': width, 'height': height, 'grid': GRID_VERSION}}))

    @staticmethod
    def validate_weather_preferences(value):
        from maeumnarae.services.weather import coordinates
        if not isinstance(value, dict) or value.get('mode') not in ('daily', 'weekly'):
            raise ValueError('날씨 표시 설정이 올바르지 않습니다.')
        location = value.get('location')
        if location is not None:
            if (not isinstance(location, dict) or not isinstance(location.get('name'), str)
                    or not 1 <= len(location['name']) <= 500):
                raise ValueError('날씨 지역 설정이 올바르지 않습니다.')
            coordinates(location.get('latitude'), location.get('longitude'))
        return deepcopy({'mode': value['mode'], 'location': location})

    def weather_preferences(self, instance_id):
        try:
            value = self._read().get('weather', {}).get(instance_id, {'mode': 'daily', 'location': None})
            return self.validate_weather_preferences(value)
        except (ValueError, AttributeError):
            raise DatabaseError('날씨 설정을 읽지 못했습니다.') from None

    def save_weather_preferences(self, instance_id, value):
        value = self.validate_weather_preferences(value)
        self._update(lambda widgets: widgets.setdefault('weather', {}).update({instance_id: value}))

    def note(self, instance_id: str) -> str:
        widgets = self._read()  # 초안도 잠금 상태에서는 반환하지 않는다.
        if instance_id in self.note_drafts:
            return clean_html(self.note_drafts[instance_id])
        return clean_html(widgets['notes'].get(instance_id, ''))

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
