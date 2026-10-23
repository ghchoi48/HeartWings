"""캘린더 목록과 월간/주간 일정 화면."""

import calendar
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta

from nicegui import run, ui

from views.delete_action import delete_button

from views.time_inputs import parse_time, time_input
from pydantic import ValidationError

from database import DatabaseError
from calendar_holidays import HOLIDAY_COLOR, korean_holidays, is_day_off
from models import CalendarInput, CalendarEvent, CalendarEventInput
from reporting import KST, STATUS_LABELS
from repositories.calendar_repo import CalendarRepository
from repositories.reporting_repo import ReportingRepository


JOURNAL_ICONS = {
    'counseling': ('edit_note', '개인상담'),
    'group': ('groups', '집단상담'),
    'special_education': ('menu_book', '특별교육'),
    'consultation': ('forum', '자문'),
}


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


def visible_days(anchor: date, mode: str) -> list[date]:
    """일요일 시작의 달력 날짜를 계산한다. 월간은 인접 월 날짜도 포함한다."""
    if mode == 'week':
        sunday = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
        return [sunday + timedelta(days=i) for i in range(7)]
    return [day for week in calendar.Calendar(firstweekday=6).monthdatescalendar(anchor.year, anchor.month) for day in week]


def event_dates(entry):
    begins = entry.starts_at.astimezone(KST)
    return begins.date(), (begins + timedelta(minutes=entry.duration_minutes) - timedelta(microseconds=1)).date()


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

    def build(self) -> None:
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            with ui.card().classes('w-full min-w-0 rounded-2xl p-5 shadow-sm'):
                with ui.row().classes('w-full items-center gap-2'):
                    self.previous_button = ui.button('이전 달', icon='chevron_left', on_click=lambda: self.shift(-1)).props('flat dense')
                    self.heading = ui.label().classes('text-xl font-bold')
                    self.next_button = ui.button('다음 달', icon='chevron_right', on_click=lambda: self.shift(1)).props('flat dense')
                    ui.button('오늘', on_click=self.today).props('outline')
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
                                ui.button('캘린더 추가', icon='add', on_click=self.open_calendar_editor).props('outline').classes('w-full')
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
                    checkbox.classes('min-w-0 break-words')
                    if item.source in ('counseling', 'holidays'):
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
        self.events_by_day = defaultdict(list)
        for event in events:
            begins = event.starts_at.astimezone(KST)
            finishes = begins + timedelta(minutes=event.duration_minutes)
            first = max(days[0], begins.date())
            last = min(days[-1], (finishes - timedelta(microseconds=1)).date())
            for offset in range((last - first).days + 1):
                self.events_by_day[first + timedelta(days=offset)].append(event)
        self.render_grid()
        self.message.text = f'선택한 캘린더 {len(selected_ids)}개 · 표시 기간 일정 {len(events)}건' if selected_ids else '캘린더 목록 버튼에서 표시할 캘린더를 선택해 주세요.'

    def render_grid(self):
        self.grid.clear()
        today = datetime.now(KST).date()
        days = visible_days(self.anchor, self.mode.value)
        hidden = ({5} if self.hide_saturday.value else set()) | ({6} if self.hide_sunday.value else set())
        columns = f'grid-cols-{7 - len(hidden)}'
        with self.grid:
            with ui.element('div').classes(f'grid {columns} w-full'):
                for index, label in enumerate(['일', '월', '화', '수', '목', '금', '토']):
                    if (index + 6) % 7 in hidden:
                        continue
                    ui.label(label).classes('text-center p-2 bg-slate-50 font-semibold ' + ('text-red-500' if index in (0, 6) else 'text-slate-600'))
            for offset in range(0, len(days), 7):
                week = [day for day in days[offset:offset + 7] if day.weekday() not in hidden]
                segments = week_event_segments(week, self.events_by_day)
                lanes = max((s[3] + 1 for s in segments), default=0)
                with ui.element('div').classes(f'relative grid {columns} w-full isolate'):
                    with ui.element('div').classes(f'absolute inset-0 grid {columns} pointer-events-none -z-10'):
                        for day in week:
                            color = 'bg-teal-50' if day == self.selected else 'bg-white'
                            ui.element('div').classes(f'border border-slate-200 {color}')
                    for col, day in enumerate(week):
                        with ui.column().classes('min-w-0 p-2 gap-1').style(f'grid-column:{col + 1}; grid-row:1'):
                            label = f'{day.month}/{day.day}' + (' · 오늘' if day == today else '')
                            button = ui.button(label, on_click=lambda day=day: self.choose(day)).props('flat dense').classes('w-full')
                            if is_day_off(day, self.holiday_days):
                                button.props('color=red-7')
                            if day.month != self.anchor.month and self.mode.value == 'month':
                                button.classes('opacity-50')
                            if day in self.holiday_days and any(item.visible and item.source == 'holidays' for item in self.calendars):
                                ui.label(self.holiday_days[day]).classes('w-full text-xs break-words').style(f'color:{HOLIDAY_COLOR}')
                    for entry, col, span, lane, first, last in segments:
                        name = entry.title if entry.source == 'custom' else entry.display_name or entry.student_name
                        caption = name if entry.all_day else f'{entry.starts_at.astimezone(KST):%H:%M} {name}'
                        style = (f'grid-column:{col + 1} / span {span}; grid-row:{lane + 2}; '
                                 f'margin:2px {"4px" if last else "0"} 2px {"4px" if first else "0"}; '
                                 f'border-radius:{"6px" if first else "0"} {"6px" if last else "0"} '
                                 f'{"6px" if last else "0"} {"6px" if first else "0"};')
                        if entry.all_day:
                            rgb = [int(entry.color[i:i + 2], 16) for i in (1, 3, 5)]
                            foreground = '#111827' if sum(v * w for v, w in zip(rgb, (0.299, 0.587, 0.114))) > 150 else '#ffffff'
                            style += f'background:{entry.color} !important; color:{foreground} !important;'
                        else:
                            style += f'color:{entry.color}; border:1px solid {entry.color};'
                        with ui.button(on_click=lambda entry=entry: self.open_event(entry)).props(
                                'unelevated dense no-caps align=left' if entry.all_day else 'flat dense no-caps align=left').classes(
                                    'min-w-0 text-xs h-7').style(style).tooltip(name) as bar:
                            bar.props['aria-label'] = caption
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
                                name = entry.title if entry.source == 'custom' else entry.display_name or entry.student_name
                                caption = f'{entry.starts_at.astimezone(KST):%H:%M} {name}'.strip()
                                with ui.button(on_click=lambda entry=entry: self.open_event(entry)).props('flat dense no-caps align=left').classes(
                                        'w-full text-xs').style(f'border-left:3px solid {entry.color}; color:{entry.color}'):
                                    ui.label(caption).classes('flex-1 min-w-0 break-words text-left')
                                    render_event_icons(entry)
                            if len(entries) > limit:
                                ui.button(f'+{len(entries) - limit}개 더 보기', on_click=lambda day=day: self.choose(day)).props('flat dense').classes('text-xs')

    async def choose(self, day: date):
        self.selected = day
        self.render_grid()

    async def open_event(self, entry):
        if entry.source == 'counseling':
            await self.on_open(entry.id)
        elif entry.source in ('group', 'consultation', 'special_education'):
            if self.on_open_linked is not None:
                await self.on_open_linked(entry)
        else:
            await self.open_event_editor(entry)

    async def open_calendar_editor(self):
        if self.editor_open:
            return
        self.calendar_menu.close()
        self.editor_open = True
        dialog = None
        try:
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-md p-6'):
                    ui.label('캘린더 추가').classes('text-xl font-bold')
                    name = ui.input('캘린더 이름', placeholder='예: 학교 일정, 상담실 운영').props('outlined maxlength=100').classes('w-full')
                    color = ui.select({'#0d9488': '청록', '#2563eb': '파랑', '#7c3aed': '보라', '#db2777': '분홍', '#ea580c': '주황'},
                                      label='색상', value='#2563eb').props('outlined').classes('w-full')
                    message = ui.label().classes('text-sm text-red-700')
                    with ui.row().classes('w-full justify-end'):
                        cancel = ui.button('취소', on_click=lambda: dialog.submit(False)).props('flat')
                        save = ui.button('추가', icon='add')

            saving = False

            async def create():
                nonlocal saving
                if saving:
                    return
                try:
                    value = CalendarInput(name=name.value, color=color.value)
                except ValidationError:
                    message.text = '캘린더 이름을 1~100자로 입력해 주세요.'
                    return
                saving = True
                for control in (name, color, save, cancel):
                    control.disable()
                try:
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
                ui.notify('캘린더를 추가했습니다.', type='positive')
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()

    async def open_event_editor(self, entry=None):
        if self.editor_open:
            return
        options = {item.id: item.name for item in self.calendars if item.source == 'custom'}
        if not options:
            ui.notify('먼저 일정 등록용 캘린더를 추가해 주세요.', type='info')
            return
        self.editor_open = True
        dialog = None
        try:
            local = entry.starts_at.astimezone(KST) if entry else datetime.combine(self.selected, time(9), KST)
            default_calendar = next((item.id for item in self.calendars if item.source == 'custom' and item.visible), next(iter(options)))
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-4xl p-6'):
                    ui.label('일정 수정' if entry else '일정 추가').classes('text-xl font-bold')
                    target = ui.select(options, label='캘린더', value=entry.calendar_id if entry else default_calendar).props('outlined').classes('w-full')
                    if entry:
                        target.disable()
                    title = ui.input('일정 제목', value=entry.title if entry else '').props('outlined maxlength=200').classes('w-full')
                    with ui.row().classes('w-full flex-nowrap items-start'):
                        all_day = ui.checkbox('종일', value=entry.all_day if entry else False).classes('shrink-0 self-center')
                        day = ui.date_input('시작 날짜', value=str(local.date())).props('outlined').classes('flex-1 min-w-0')
                        start = time_input('시작 시간', value=local.strftime('%H:%M')).props('outlined').classes('flex-1 min-w-0')
                        end_time = local + timedelta(minutes=entry.duration_minutes if entry else 60)
                        end_date = (end_time - timedelta(microseconds=1)).date() if entry and entry.all_day else end_time.date()
                        ui.label('~').classes('self-center shrink-0 text-slate-500')
                        end = time_input('종료 시간', value=end_time.strftime('%H:%M')).props('outlined').classes('flex-1 min-w-0')
                        end_day = ui.date_input('종료 날짜', value=str(end_date)).props('outlined').classes('flex-1 min-w-0')
                    ui.label('종일 일정은 시작 날짜부터 종료 날짜까지 포함합니다.').classes('text-xs text-slate-500')
                    location = ui.input('장소', value=entry.location if entry else '').props('outlined maxlength=200').classes('w-full')
                    content = ui.textarea('내용', value=entry.content if entry else '').props('outlined maxlength=20000').classes('w-full')
                    message = ui.label().classes('text-sm text-red-700')
                    with ui.row().classes('w-full justify-end'):
                        cancel = ui.button('작성 닫기').props('flat')
                        save = ui.button('일정 저장', icon='save')
                        if entry:
                            async def after_deleted():
                                dialog.submit(False)
                                await self.reload()
                            delete = delete_button(self.repository.database, 'event', lambda: entry, after_deleted, blocked=lambda: saving)
            fields = (target, title, day, start, end, end_day, all_day, location, content)
            original = tuple(field.value for field in fields)
            saving = False

            previous_day = day.value

            def sync_end_day(event):
                nonlocal previous_day
                try:
                    new_day = date.fromisoformat(event.value or '').isoformat()
                except ValueError:
                    return
                if end_day.value == previous_day:
                    end_day.value = new_day
                previous_day = new_day

            day.on_value_change(sync_end_day)

            def update_time_fields():
                end_day.set_visibility(all_day.value)
                for element in (start, end):
                    element.set_visibility(not all_day.value)
                start.set_enabled(not saving and not all_day.value)
                end.set_enabled(not saving and not all_day.value)

            all_day.on_value_change(update_time_fields)
            update_time_fields()

            async def close():
                if saving:
                    return
                if original != tuple(field.value for field in fields):
                    with ui.dialog().props('persistent') as confirm, ui.card():
                        ui.label('저장하지 않은 내용을 버릴까요?')
                        ui.button('계속 작성', on_click=lambda: confirm.submit(False))
                        ui.button('변경 내용 버리기', on_click=lambda: confirm.submit(True))
                    discard = await confirm
                    confirm.delete()
                    if not discard:
                        return
                dialog.submit(False)

            async def store():
                nonlocal saving
                if saving:
                    return
                try:
                    moment = datetime.combine(date.fromisoformat(day.value), time.min if all_day.value else parse_time(start.value), KST)
                    if not 2 <= moment.year <= 9998:
                        raise ValueError
                    final_day = date.fromisoformat(end_day.value) if all_day.value else moment.date()
                    if not 2 <= final_day.year <= 9998 or final_day < moment.date():
                        message.text = '종료 날짜는 시작 날짜 이후여야 합니다.'
                        return
                    ends_at = datetime.combine(final_day, time.min if all_day.value else parse_time(end.value), KST)
                    if not all_day.value and ends_at < moment:
                        message.text = '종료 시간은 시작 시간보다 이를 수 없습니다.'
                        return
                    if all_day.value or ends_at == moment:
                        ends_at += timedelta(days=1)
                    if ends_at <= moment:
                        message.text = '종료 날짜와 시간은 시작 날짜와 시간보다 이후여야 합니다.'
                        return
                    duration_minutes = (ends_at - moment).total_seconds() / 60
                    value = CalendarEventInput(calendar_id=target.value, title=title.value, starts_at=moment,
                                               duration_minutes=duration_minutes,
                                               all_day=all_day.value,
                                               location=location.value or '', content=content.value or '')
                except (ValueError, TypeError):
                    message.text = '캘린더, 제목(1~200자), 날짜·시작 시간·종료 시간, 장소(200자 이내), 내용(20,000자 이내)을 확인해 주세요.'
                    return
                saving = True
                for field in (*fields, save, cancel):
                    field.disable()
                if entry:
                    delete.disable()
                try:
                    await run.io_bound(self.repository.save_event, value, entry.id if entry else None)
                    dialog.submit(True)
                except DatabaseError as error:
                    message.text = str(error)
                finally:
                    saving = False
                    for field in (*fields, save, cancel):
                        field.enable()
                    if entry:
                        delete.enable()
                    update_time_fields()
                    if entry:
                        target.disable()

            cancel.on_click(close)
            save.on_click(store)
            if await dialog:
                self.anchor = self.selected = date.fromisoformat(day.value)
                await self.reload()
                ui.notify('일정을 저장했습니다.', type='positive')
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()
