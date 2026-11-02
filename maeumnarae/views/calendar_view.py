"""캘린더 목록과 월간/주간 일정 화면."""

from collections.abc import Awaitable, Callable
import json
from datetime import date, datetime, timedelta

from nicegui import run, ui

from maeumnarae.views.calendar_event_editor import open_event_editor
from maeumnarae.services.calendar_dates import visible_days, event_dates, events_by_date

from pydantic import ValidationError

from maeumnarae.core.database import DatabaseError
from maeumnarae.services.calendar_holidays import HOLIDAY_COLOR, korean_holidays
from maeumnarae.core.models import CalendarInput, CalendarEvent
from maeumnarae.services.reporting import KST, STATUS_LABELS
from maeumnarae.repositories.calendar_repo import CalendarRepository
from maeumnarae.repositories.reporting_repo import ReportingRepository
from maeumnarae.services.school_calendar import load_school_events, SOURCE_URL


JOURNAL_ICONS = {
    'counseling': ('edit_note', '개인상담'),
    'group': ('groups', '집단상담'),
    'special_education': ('menu_book', '특별교육'),
    'education_event': ('event', '교육/행사'),
    'consultation': ('forum', '자문'),
}

HIDE_DROP_GUIDES = '''
    document.querySelectorAll('[data-calendar-drop-guide]').forEach(guide => {
        guide.style.display = 'none';
    });
'''
RESET_CALENDAR_DRAG = HIDE_DROP_GUIDES + '''
    document.querySelectorAll('[data-calendar-drop-surface]').forEach(surface => {
        surface.calendarDrag = null;
    });
'''


def event_name(entry: CalendarEvent) -> str:
    """큰 캘린더와 홈 위젯에서 같은 일정 이름을 표시한다."""
    if entry.source == 'special_education':
        return entry.student_name
    if entry.source == 'custom':
        return entry.title
    return entry.display_name or entry.student_name or entry.title


def event_caption(entry: CalendarEvent) -> str:
    name = event_name(entry)
    if entry.all_day:
        return name
    return f'{entry.starts_at.astimezone(KST):%H:%M} {name}'.strip()


def render_event_icons(entry: CalendarEvent) -> None:
    """상태와 일지 종류를 나란히 표시한다."""
    if entry.status is not None:
        ui.icon({'scheduled': 'schedule', 'completed': 'check_circle',
                 'cancelled': 'cancel'}[entry.status], size='16px').classes('shrink-0 ml-1').props(
                     f'role=img aria-label="{STATUS_LABELS[entry.status]}"').tooltip(STATUS_LABELS[entry.status])
    if entry.source in JOURNAL_ICONS:
        icon, label = JOURNAL_ICONS[entry.source]
        ui.icon(icon, size='16px').classes('shrink-0 ml-1').props(
            f'role=img aria-label="{label}"').tooltip(label)


def week_event_segments(days, events_by_day):
    """날짜를 가로지르는 막대에 겹치지 않는 행을 배정한다."""
    entries = {(e.source, e.id): e for day in days for e in events_by_day.get(day, [])
               if e.all_day or event_dates(e)[0] != event_dates(e)[1]}
    occupied = []
    segments = []
    for entry in sorted(entries.values(), key=lambda e: (e.starts_at, -e.duration_minutes, e.source, e.id)):
        first, last = event_dates(entry)
        covered = [i for i, day in enumerate(days) if first <= day <= last]
        left, right = covered[0], covered[-1]
        lane = next((i for i, end in enumerate(occupied) if end < left), len(occupied))
        if lane == len(occupied):
            occupied.append(right)
        else:
            occupied[lane] = right
        segments.append((entry, left, right - left + 1, lane, first >= days[0], last <= days[-1]))
    return segments


def show_school_event(entry):
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg p-6'):
        ui.label(entry.title).classes('text-xl font-bold')
        ui.label(f'{entry.starts_at.astimezone(KST):%Y.%m.%d} · 학사일정 (NEIS)')
        ui.label(entry.content).classes('whitespace-pre-wrap break-words')
        ui.label('나이스에서 제공하는 읽기 전용 일정입니다. 학교 사정에 따라 변경될 수 있습니다.').classes('text-sm text-slate-500')
        ui.link('출처: 나이스 교육정보 개방 포털', SOURCE_URL, new_tab=True)
        ui.button('닫기', on_click=dialog.close).props('flat')
    dialog.open()


class CalendarView:
    def __init__(self, repository: ReportingRepository, on_open: Callable[[int], Awaitable[None]],
                 on_open_linked: Callable[[CalendarEvent], Awaitable[None]] | None = None):
        self.repository = CalendarRepository(repository.database)
        self.on_open = on_open
        self.on_open_linked = on_open_linked
        self.anchor = datetime.now(KST).date()
        self.selected = self.anchor
        self.count_request = 0
        self.calendars = []
        self.events_by_day = {}
        self.holiday_days = {}
        self.editor_open = False
        self.loaded_revision = None
        self.refreshing = False
        self.moving_event = False

    def build(self) -> None:
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            with ui.card().classes('w-full min-w-0 rounded-2xl p-5 shadow-sm'):
                with ui.row().classes('w-full items-center gap-2'):
                    self.previous_button = ui.button('이전 달', icon='chevron_left', on_click=lambda: self.shift(-1)).props('flat dense')
                    self.heading = ui.label().classes('text-xl font-bold')
                    self.next_button = ui.button('다음 달', icon='chevron_right', on_click=lambda: self.shift(1)).props('flat dense')
                    ui.button('오늘', on_click=self.today).props('outline')
                    ui.button('새로고침', icon='refresh', on_click=self.reload).props('flat')
                    ui.space()
                    with ui.button('캘린더 목록', icon='calendar_month').props('outline icon-right=expand_more'):
                        self.calendar_menu = ui.menu().props('anchor="bottom right" self="top right"').classes('rounded-xl shadow-lg')
                        with self.calendar_menu:
                            with ui.column().classes('w-80 max-w-[85vw] gap-3 p-4'):
                                ui.label('표시할 캘린더').classes('text-base font-semibold')
                                self.calendar_list = ui.column().classes('w-full gap-3 max-h-80 overflow-y-auto')
                                self.list_message = ui.label().classes('text-sm text-slate-500')
                                ui.separator()
                                self.hide_saturday = ui.checkbox('토요일 감추기', on_change=lambda: self.render_grid())
                                self.hide_sunday = ui.checkbox('일요일 감추기', on_change=lambda: self.render_grid())
                                ui.separator()
                                ui.button('캘린더 추가', icon='add', on_click=lambda: self.open_calendar_editor()).props('outline').classes('w-full')
                    self.mode = ui.toggle({'month': '월간', 'week': '주간'}, value='month', on_change=self.change_mode)
                    self.add_event = ui.button('일정 추가', icon='add', on_click=lambda: self.open_event_editor())
                    self.add_event.disable()
                self.message = ui.label().classes('text-sm text-slate-500')
                with ui.element('div').classes('w-full overflow-x-auto'):
                    self.grid = ui.column().classes('w-full gap-0').style('min-width:700px')
        ui.timer(0.01, self.reload, once=True)
        ui.timer(0.5, self.refresh_if_changed)

    def render_calendars(self):
        self.calendar_list.clear()
        with self.calendar_list:
            for item in self.calendars:
                with ui.row().classes('w-full items-center flex-nowrap gap-2'):
                    ui.element('span').classes('w-3 h-3 rounded-full shrink-0').style(f'background-color:{item.color}')
                    checkbox = ui.checkbox(item.name, value=item.visible,
                        on_change=lambda event, calendar_id=item.id: self.toggle_calendar(calendar_id, event.value))
                    checkbox.classes('flex-1 min-w-0 break-words')
                    if item.source == 'custom':
                        ui.button(icon='edit', on_click=lambda item=item: self.open_calendar_editor(item)).props(
                            'flat round dense aria-label="캘린더 수정"').tooltip('캘린더 수정')
                        ui.button(icon='delete_outline', on_click=lambda item=item: self.delete_calendar(item)).props(
                            'flat round dense color=negative aria-label="캘린더 삭제"').tooltip('캘린더 삭제')
                    if item.source in ('counseling', 'holidays', 'neis'):
                        ui.badge('연동').props('outline').classes('shrink-0')
        self.list_message.text = '체크한 캘린더의 일정만 표시합니다.'
        self.add_event.set_enabled(any(item.source == 'custom' for item in self.calendars))

    async def toggle_calendar(self, calendar_id, visible):
        # 저장 중에는 체크박스를 잠가 빠른 연속 변경이 역순으로 저장되지 않게 한다.
        self.count_request += 1
        for element in self.calendar_list.descendants():
            if isinstance(element, ui.checkbox):
                element.disable()
        try:
            await run.io_bound(self.repository.set_visible, calendar_id, visible)
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
        await self.reload()

    async def change_mode(self) -> None:
        """선택 날짜를 기준으로 월간/주간 범위를 전환한다."""
        self.anchor = self.selected
        await self.reload()

    async def refresh_if_changed(self) -> None:
        """다른 화면에서 커밋한 변경을 반영하고 편집 중에는 갱신을 미룬다."""
        if self.refreshing or self.editor_open or self.loaded_revision == self.repository.database.write_revision:
            return
        self.refreshing = True
        try:
            await self.reload()
        finally:
            self.refreshing = False

    async def today(self) -> None:
        self.anchor = self.selected = datetime.now(KST).date()
        await self.reload()

    async def shift(self, direction: int) -> None:
        """월/주 단위로 이동한다."""
        try:
            if self.mode.value == 'week':
                day = self.anchor + timedelta(days=direction * 7)
            else:
                month = self.anchor.year * 12 + self.anchor.month - 1 + direction
                year, index = divmod(month, 12)
                day = date(year, index + 1, 1)
            if not 2 <= day.year <= 9998:
                raise ValueError
        except (ValueError, OverflowError):
            self.message.text = '이동 가능한 날짜 범위를 벗어났습니다.'
            return
        self.anchor = self.selected = day
        await self.reload()

    async def reload(self) -> None:
        self.count_request += 1
        request = self.count_request
        days = visible_days(self.anchor, self.mode.value)
        revision = self.repository.database.write_revision
        self.previous_button.text = '이전 주' if self.mode.value == 'week' else '이전 달'
        self.next_button.text = '다음 주' if self.mode.value == 'week' else '다음 달'
        self.heading.text = f'{self.anchor:%Y년 %m월}' if self.mode.value == 'month' else f'{days[0]:%Y.%m.%d} ~ {days[-1]:%m.%d}'
        self.grid.clear()
        self.events_by_day = {}
        self.holiday_days = {}
        self.message.text = '일정을 불러오는 중입니다…'
        try:
            calendars = await run.io_bound(self.repository.list)
            if request != self.count_request:
                return
            selected_ids = [item.id for item in calendars if item.visible]
            event_calendar_ids = [item.id for item in calendars if item.visible and item.source != 'holidays']
            events = await run.io_bound(self.repository.events, days[0], days[-1], event_calendar_ids)
            holiday_days = await run.io_bound(korean_holidays, days[0], days[-1])
            school_events, school_message = await run.io_bound(
                load_school_events, self.repository.database, calendars, days[0], days[-1])
            events.extend(school_events)
        except DatabaseError as error:
            if request == self.count_request:
                self.message.text = str(error)
                self.render_calendars()
            return
        if request != self.count_request:
            return
        self.loaded_revision = revision
        self.calendars = calendars
        self.holiday_days = holiday_days
        self.render_calendars()
        self.events_by_day = events_by_date(events, days)
        self.render_grid()
        self.message.text = f'선택한 캘린더 {len(selected_ids)}개 · 표시 기간 일정 {len(events)}건' if selected_ids else '캘린더 목록 버튼에서 표시할 캘린더를 선택해 주세요.'
        if school_message:
            self.message.text += ' · ' + school_message

    def render_grid(self):
        self.grid.clear()
        self.grid.props('data-calendar-drop-surface')
        today = datetime.now(KST).date()
        days = visible_days(self.anchor, self.mode.value)
        hidden = ({5} if self.hide_saturday.value else set()) | ({6} if self.hide_sunday.value else set())
        columns = f'grid-cols-{7 - len(hidden)}'
        with self.grid:
            with ui.element('div').classes(f'grid {columns} w-full'):
                for index, label in enumerate(['일', '월', '화', '수', '목', '금', '토']):
                    if (index + 6) % 7 in hidden:
                        continue
                    ui.label(label).classes('text-center p-2 bg-slate-50 font-semibold ' + (
                        'text-red-500' if index == 0 else 'text-blue-500' if index == 6 else 'text-slate-600'))
            for offset in range(0, len(days), 7):
                week = [day for day in days[offset:offset + 7] if day.weekday() not in hidden]
                segments = week_event_segments(week, self.events_by_day)
                lanes = max((s[3] + 1 for s in segments), default=0)
                with ui.element('div').classes(f'relative grid {columns} w-full isolate') as week_grid:
                    self.bind_week_interactions(week_grid, week)
                    with ui.element('div').classes(f'absolute inset-0 grid {columns} pointer-events-none -z-10'):
                        for day in week:
                            selection = ('ring-2 ring-inset app-primary-ring'
                                         if day == self.selected else '')
                            ui.element('div').classes(f'border border-slate-200 bg-white {selection}')
                    for col, day in enumerate(week):
                        with ui.column().classes('min-w-0 p-2 gap-1').style(f'grid-column:{col + 1}; grid-row:1'):
                            label = f'{day.month}/{day.day}' + (' · 오늘' if day == today else '')
                            button = ui.button(label).props(
                                f'flat dense data-calendar-date aria-pressed={str(day == self.selected).lower()}').classes('w-full')
                            button.on('click', lambda e, day=day: self.choose(day), js_handler='''event => {
                                const button = event.currentTarget;
                                clearTimeout(button.calendarClickTimer);
                                button.calendarClickTimer = setTimeout(() => emit({}), 350);
                            }''')
                            if day.weekday() == 6 or day in self.holiday_days:
                                button.props('color=red-7')
                            elif day.weekday() == 5:
                                button.props('color=blue-7')
                            if day.month != self.anchor.month and self.mode.value == 'month' and day != self.selected:
                                button.classes('opacity-50')
                            if day in self.holiday_days and any(item.visible and item.source == 'holidays' for item in self.calendars):
                                ui.label(self.holiday_days[day]).classes('w-full text-xs break-words').style(f'color:{HOLIDAY_COLOR}')
                    for entry, col, span, lane, first, last in segments:
                        name = event_name(entry)
                        caption = event_caption(entry)
                        style = (f'grid-column:{col + 1} / span {span}; grid-row:{lane + 2}; '
                                 f'margin:2px {"4px" if last else "0"} 2px {"4px" if first else "0"}; '
                                 f'border-radius:{"6px" if first else "0"} {"6px" if last else "0"} '
                                 f'{"6px" if last else "0"} {"6px" if first else "0"};')
                        if entry.all_day:
                            rgb = [int(entry.color[i:i + 2], 16) for i in (1, 3, 5)]
                            foreground = '#111827' if sum(v * w for v, w in zip(rgb, (0.299, 0.587, 0.114))) > 150 else '#ffffff'
                            style += f'background:{entry.color} !important; color:{foreground} !important;'
                        else:
                            style += f'color:var(--app-calendar-timed-text, #000000) !important; border:1px solid {entry.color};'
                        with ui.button(on_click=lambda entry=entry: self.open_event(entry)).props(
                                'unelevated dense no-caps align=left' if entry.all_day else 'flat dense no-caps align=left').classes(
                                    'min-w-0 text-xs h-7').style(style).tooltip(name) as bar:
                            bar.props['aria-label'] = caption
                            self.bind_event_drag(bar, entry)
                            if first:
                                ui.label(caption).classes('flex-1 min-w-0 truncate text-left')
                                render_event_icons(entry)
                    for col, day in enumerate(week):
                        height = 'min-h-64' if self.mode.value == 'week' else 'min-h-20'
                        with ui.column().classes(f'min-w-0 p-2 gap-1 {height} max-h-96 overflow-y-auto').style(
                                f'grid-column:{col + 1}; grid-row:{lanes + 2}'):
                            entries = [e for e in self.events_by_day.get(day, [])
                                       if not e.all_day and event_dates(e)[0] == event_dates(e)[1]]
                            limit = len(entries) if day == self.selected else (10 if self.mode.value == 'week' else 3)
                            for entry in entries[:limit]:
                                caption = event_caption(entry)
                                with ui.button(on_click=lambda entry=entry: self.open_event(entry)).props('flat dense no-caps align=left').classes(
                                        'w-full text-xs').style(f'border-left:3px solid {entry.color}; color:var(--app-calendar-timed-text, #000000) !important') as event_button:
                                    self.bind_event_drag(event_button, entry)
                                    ui.label(caption).classes('flex-1 min-w-0 break-words text-left')
                                    render_event_icons(entry)
                            if len(entries) > limit:
                                ui.button(f'+{len(entries) - limit}개 더 보기', on_click=lambda day=day: self.choose(day)).props('flat dense').classes('text-xs')

    def bind_week_interactions(self, element, week):
        dates = json.dumps([day.isoformat() for day in week])
        element.props(f"data-calendar-days='{dates}'")
        # One overlay per visible date also previews ranges crossing week boundaries.
        for column, day in enumerate(week):
            ui.element('div').props(f'data-calendar-drop-guide={day.isoformat()} aria-hidden=true').classes(
                'absolute inset-y-0 pointer-events-none z-20 border-2 border-dashed '
                'app-primary-border rounded-md').style(
                    f'display:none; left:{column * 100 / len(week)}%; width:{100 / len(week)}%')
        # Hit-test the week grid so spanning bars and hidden weekends use the same columns.
        hit_test = f'''
            const dates = {dates};
            const rect = event.currentTarget.getBoundingClientRect();
            const column = Math.max(0, Math.min(dates.length - 1,
                Math.floor((event.clientX - rect.left) / rect.width * dates.length)));
        '''
        element.on('dblclick', lambda e: self.create_on_date(date.fromisoformat(e.args)), js_handler='''event => {
            const button = event.target.closest('button');
            if (button && !button.hasAttribute('data-calendar-date')) return;
            if (button) clearTimeout(button.calendarClickTimer);
            event.preventDefault();
        ''' + hit_test + '''emit(dates[column]); }''')
        element.on('dragover', js_handler='''event => {
            if (!Array.from(event.dataTransfer.types).includes('application/x-maeumnarae-event')) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
        ''' + hit_test + '''
            const surface = event.currentTarget.closest('[data-calendar-drop-surface]');
            const drag = surface.calendarDrag;
            if (!drag) return;
            const shift = Date.parse(dates[column]) - Date.parse(drag.origin);
            const first = Date.parse(drag.first) + shift;
            const last = Date.parse(drag.last) + shift;
            surface.querySelectorAll('[data-calendar-drop-guide]').forEach(guide => {
                const day = Date.parse(guide.dataset.calendarDropGuide);
                guide.style.display = day >= first && day <= last ? 'block' : 'none';
            });
        }''')
        element.on('dragleave', js_handler='''event => {
            if (event.relatedTarget && event.currentTarget.contains(event.relatedTarget)) return;
        ''' + HIDE_DROP_GUIDES + '}')
        element.on('drop', self.drop_event, js_handler='''event => {
        ''' + RESET_CALENDAR_DRAG + '''
            const raw = event.dataTransfer.getData('application/x-maeumnarae-event');
            if (!raw) return;
            event.preventDefault();
        ''' + hit_test + '''
            try { emit({...JSON.parse(raw), target: dates[column]}); } catch (_) {}
        }''')

    def bind_event_drag(self, element, entry):
        if entry.source != 'custom':
            return
        element.props('draggable=true').classes('cursor-grab active:cursor-grabbing')
        first, last = event_dates(entry)
        period = json.dumps({'first': first.isoformat(), 'last': last.isoformat()})
        element.on('dragend', js_handler='event => {' + RESET_CALENDAR_DRAG + '}')
        element.on('dragstart', js_handler='''event => {
        ''' + RESET_CALENDAR_DRAG + '''
            const week = event.currentTarget.closest('[data-calendar-days]');
            const dates = JSON.parse(week.dataset.calendarDays);
            const rect = week.getBoundingClientRect();
            const column = Math.max(0, Math.min(dates.length - 1,
                Math.floor((event.clientX - rect.left) / rect.width * dates.length)));
            week.closest('[data-calendar-drop-surface]').calendarDrag = {
                ...''' + period + ''', origin: dates[column]
            };
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('application/x-maeumnarae-event', JSON.stringify({
                id: ''' + str(entry.id) + ''', origin: dates[column]
            }));
        }''')

    async def drop_event(self, event):
        if self.moving_event or self.editor_open:
            return
        try:
            entry_id = int(event.args['id'])
            origin = date.fromisoformat(event.args['origin'])
            target = date.fromisoformat(event.args['target'])
            entry = next((e for e in self.events_by_day.get(origin, [])
                          if e.id == entry_id and e.source == 'custom'), None)
            if entry is None or target not in visible_days(self.anchor, self.mode.value):
                return
        except (KeyError, TypeError, ValueError):
            return
        if origin == target:
            return
        self.moving_event = True
        try:
            await run.io_bound(self.repository.move_event, entry.id, entry.starts_at, (target - origin).days)
            self.selected = target
            await self.reload()
            ui.notify('일정을 이동했습니다.', type='positive')
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
            await self.reload()
        finally:
            self.moving_event = False

    async def create_on_date(self, day: date):
        if self.editor_open or self.moving_event:
            return
        self.selected = day
        self.render_grid()
        await self.open_event_editor()

    async def choose(self, day: date):
        self.selected = day
        self.render_grid()

    async def open_event(self, entry):
        if entry.source == 'neis':
            show_school_event(entry)
        elif entry.source == 'counseling':
            await self.on_open(entry.id)
        elif entry.source in ('group', 'consultation', 'special_education', 'education_event'):
            if self.on_open_linked is not None:
                await self.on_open_linked(entry)
        else:
            await self.open_event_editor(entry)

    async def open_calendar_editor(self, item=None):
        if self.editor_open or (item is not None and item.source != 'custom'):
            return
        self.calendar_menu.close()
        self.editor_open = True
        dialog = None
        try:
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-md p-6'):
                    ui.label('캘린더 수정' if item else '캘린더 추가').classes('text-xl font-bold')
                    name = ui.input('캘린더 이름', value=item.name if item else '', placeholder='예: 학교 일정, 상담실 운영').props('outlined maxlength=100').classes('w-full')
                    color = ui.color_input('색상', value=item.color if item else '#2563eb',
                                           preview=True).props('outlined').classes('w-full')
                    color.picker.q_color.props('format-model=hex')
                    message = ui.label().classes('text-sm text-red-700')
                    with ui.row().classes('w-full justify-end'):
                        cancel = ui.button('취소', on_click=lambda: dialog.submit(False)).props('flat')
                        save = ui.button('저장' if item else '추가', icon='save' if item else 'add')

            saving = False

            async def create():
                nonlocal saving
                if saving:
                    return
                try:
                    value = CalendarInput(name=name.value, color=color.value)
                except ValidationError:
                    message.text = '캘린더 이름(1~100자)과 색상(#RRGGBB 형식)을 확인해 주세요.'
                    return
                saving = True
                for control in (name, color, save, cancel):
                    control.disable()
                try:
                    if item:
                        await run.io_bound(self.repository.update, item.id, value)
                    else:
                        await run.io_bound(self.repository.create, value)
                    dialog.submit(True)
                except DatabaseError as error:
                    message.text = str(error)
                finally:
                    saving = False
                    for control in (name, color, save, cancel):
                        control.enable()
            save.on_click(create)
            if await dialog:
                await self.reload()
                ui.notify('캘린더를 수정했습니다.' if item else '캘린더를 추가했습니다.', type='positive')
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()

    async def delete_calendar(self, item):
        if self.editor_open or item.source != 'custom':
            return
        self.calendar_menu.close()
        self.editor_open = True
        dialog = None
        try:
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-md p-6'):
                    ui.label('캘린더 삭제').classes('text-xl font-bold')
                    ui.label(f'“{item.name}” 캘린더를 삭제할까요?').classes('break-words')
                    ui.label('이 캘린더에 등록된 일정도 모두 삭제되며 되돌릴 수 없습니다.').classes('text-red-700')
                    message = ui.label().classes('text-sm text-red-700')
                    with ui.row().classes('w-full justify-end'):
                        cancel = ui.button('취소', on_click=lambda: dialog.submit(False)).props('flat')
                        confirm = ui.button('삭제', icon='delete_outline').props('color=negative')
            deleting = False

            async def remove():
                nonlocal deleting
                if deleting:
                    return
                deleting = True
                cancel.disable()
                confirm.disable()
                try:
                    await run.io_bound(self.repository.delete, item.id)
                    dialog.submit(True)
                except DatabaseError as error:
                    message.text = str(error)
                finally:
                    deleting = False
                    cancel.enable()
                    confirm.enable()

            confirm.on_click(remove)
            if await dialog:
                await self.reload()
                ui.notify('캘린더를 삭제했습니다.', type='positive')
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()

    async def open_event_editor(self, entry=None):
        if self.editor_open:
            return
        self.editor_open = True

        async def changed(day):
            if day is not None:
                self.anchor = self.selected = day
            await self.reload()

        try:
            await open_event_editor(self.repository, self.calendars, self.selected, changed, entry)
        finally:
            self.editor_open = False
