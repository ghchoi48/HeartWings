"""캘린더 목록과 월간/주간 일정 화면."""

import calendar
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta

from nicegui import run, ui

from views.time_inputs import parse_time, time_input
from pydantic import ValidationError

from database import DatabaseError
from calendar_holidays import HOLIDAY_COLOR, korean_holidays, is_day_off
from models import CalendarInput, CalendarEventInput
from reporting import KST, STATUS_LABELS
from repositories.calendar_repo import CalendarRepository
from repositories.reporting_repo import ReportingRepository


def visible_days(anchor: date, mode: str) -> list[date]:
    """일요일 시작의 달력 날짜를 계산한다. 월간은 인접 월 날짜도 포함한다."""
    if mode == 'week':
        sunday = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
        return [sunday + timedelta(days=i) for i in range(7)]
    return [day for week in calendar.Calendar(firstweekday=6).monthdatescalendar(anchor.year, anchor.month) for day in week]


class CalendarView:
    def __init__(self, repository: ReportingRepository, on_open: Callable[[int], Awaitable[None]]):
        self.repository = CalendarRepository(repository.database)
        self.on_open = on_open
        self.anchor = datetime.now(KST).date()
        self.selected = self.anchor
        self.count_request = 0
        self.calendars = []
        self.events_by_day = {}
        self.holiday_days = {}
        self.editor_open = False

    def build(self) -> None:
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            ui.label('캘린더').classes('text-3xl font-bold text-slate-800')
            ui.label('표시할 캘린더를 선택하고 일정을 확인하세요. · 한국 표준시').classes('text-slate-500')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[260px_minmax(0,1fr)] items-start gap-6'):
                with ui.card().classes('w-full min-w-0 rounded-2xl p-5 shadow-sm'):
                    ui.label('캘린더 목록').classes('text-xl font-bold')
                    ui.button('캘린더 추가', icon='add', on_click=self.open_calendar_editor).props('outline').classes('w-full')
                    ui.separator()
                    self.calendar_list = ui.column().classes('w-full gap-3')
                    self.list_message = ui.label().classes('text-sm text-slate-500')
                with ui.column().classes('w-full min-w-0 gap-5'):
                    with ui.card().classes('w-full min-w-0 rounded-2xl p-5 shadow-sm'):
                        with ui.row().classes('w-full items-center gap-2'):
                            ui.button('이전 기간', icon='chevron_left', on_click=lambda: self.shift(-1)).props('flat dense')
                            self.heading = ui.label().classes('text-xl font-bold')
                            ui.button('다음 기간', icon='chevron_right', on_click=lambda: self.shift(1)).props('flat dense')
                            ui.button('오늘', on_click=self.today).props('outline')
                            ui.space()
                            self.mode = ui.toggle({'month': '월간', 'week': '주간'}, value='month', on_change=self.change_mode)
                        with ui.row().classes('w-full items-center gap-3'):
                            self.date_input = ui.date_input('기준 날짜', value=str(self.anchor)).props('outlined dense').classes('w-44')
                            ui.button('날짜로 이동', on_click=self.jump).props('flat')
                            self.status = ui.select({'all': '전체 상태', **STATUS_LABELS}, value='all', label='일정 상태', on_change=self.change_status).props('outlined dense').classes('w-36')
                            ui.button('캘린더 새로고침', icon='refresh', on_click=self.reload).props('flat')
                            self.add_event = ui.button('일정 추가', icon='add', on_click=lambda: self.open_event_editor())
                            self.add_event.disable()
                        self.message = ui.label().classes('text-sm text-slate-500')
                        with ui.element('div').classes('w-full overflow-x-auto'):
                            self.grid = ui.column().classes('w-full gap-0').style('min-width:700px')
        ui.timer(0.01, self.reload, once=True)

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

    async def change_status(self) -> None:
        """선택한 상태로 달력의 일정을 필터링한다."""
        await self.reload()

    async def jump(self) -> None:
        """입력 날짜로 이동한다. datetime의 양 끝 경계는 달력 여백 계산을 위해 제외한다."""
        try:
            day = date.fromisoformat(self.date_input.value or '')
            if not 2 <= day.year <= 9998:
                raise ValueError
        except ValueError:
            self.message.text = '올바른 날짜를 입력해 주세요 (0002~9998년).'
            return
        self.anchor = self.selected = day
        await self.reload()

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
        self.date_input.value = str(self.anchor)
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
            events = await run.io_bound(self.repository.events, days[0], days[-1], event_calendar_ids,
                                       None if self.status.value == 'all' else self.status.value)
            holiday_days = await run.io_bound(korean_holidays, days[0], days[-1])
        except DatabaseError as error:
            if request == self.count_request:
                self.message.text = str(error)
                self.render_calendars()
            return
        if request != self.count_request:
            return
        self.calendars = calendars
        self.holiday_days = holiday_days
        self.render_calendars()
        self.events_by_day = defaultdict(list)
        for event in events:
            self.events_by_day[event.starts_at.astimezone(KST).date()].append(event)
        self.render_grid()
        self.message.text = f'선택한 캘린더 {len(selected_ids)}개 · 표시 기간 일정 {len(events)}건' if selected_ids else '왼쪽 목록에서 표시할 캘린더를 선택해 주세요.'

    def render_grid(self):
        self.grid.clear()
        today = datetime.now(KST).date()
        with self.grid:
            with ui.element('div').classes('grid grid-cols-7 w-full'):
                for index, label in enumerate(['일', '월', '화', '수', '목', '금', '토']):
                    ui.label(label).classes('text-center p-2 bg-slate-50 font-semibold ' + ('text-red-500' if index in (0, 6) else 'text-slate-600'))
                for day in visible_days(self.anchor, self.mode.value):
                    color = 'bg-teal-50' if day == self.selected else 'bg-white'
                    height = 'min-h-80' if self.mode.value == 'week' else 'min-h-32'
                    with ui.column().classes(f'min-w-0 border border-slate-200 p-2 gap-1 {height} {color} max-h-96 overflow-y-auto'):
                        label = f'{day.month}/{day.day}' + (' · 오늘' if day == today else '')
                        button = ui.button(label, on_click=lambda day=day: self.choose(day)).props('flat dense').classes('w-full')
                        if is_day_off(day, self.holiday_days):
                            button.props('color=red-7')
                        if day.month != self.anchor.month and self.mode.value == 'month':
                            button.classes('opacity-50')
                        if day in self.holiday_days and any(item.visible and item.source == 'holidays' for item in self.calendars):
                            ui.label(self.holiday_days[day]).classes('w-full text-xs break-words').style(f'color:{HOLIDAY_COLOR}')
                        entries = self.events_by_day.get(day, [])
                        limit = len(entries) if day == self.selected else (10 if self.mode.value == 'week' else 3)
                        for entry in entries[:limit]:
                            caption = f'{entry.starts_at.astimezone(KST):%H:%M} {entry.student_name} {entry.title}'.strip()
                            ui.button(caption, on_click=lambda entry=entry: self.open_event(entry)).props('flat dense no-caps align=left').classes(
                                'w-full text-xs break-words').style(f'border-left:3px solid {entry.color}; color:{entry.color}').tooltip(entry.calendar_name)
                        if len(entries) > limit:
                            ui.button(f'+{len(entries) - limit}개 더 보기', on_click=lambda day=day: self.choose(day)).props('flat dense').classes('text-xs')

    async def choose(self, day: date):
        self.selected = day
        self.render_grid()

    async def open_event(self, entry):
        if entry.source == 'counseling':
            await self.on_open(entry.id)
        else:
            await self.open_event_editor(entry)

    async def open_calendar_editor(self):
        if self.editor_open:
            return
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
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-2xl p-6'):
                    ui.label('일정 수정' if entry else '일정 추가').classes('text-xl font-bold')
                    target = ui.select(options, label='캘린더', value=entry.calendar_id if entry else default_calendar).props('outlined').classes('w-full')
                    if entry:
                        target.disable()
                    title = ui.input('일정 제목', value=entry.title if entry else '').props('outlined maxlength=200').classes('w-full')
                    with ui.row().classes('w-full items-start'):
                        day = ui.date_input('날짜', value=str(local.date())).props('outlined').classes('grow')
                        start = time_input('시각', value=local.strftime('%H:%M')).props('outlined').classes('w-40')
                        duration = ui.number('시간(분)', value=entry.duration_minutes if entry else 60, min=1, max=1440, step=1).props('outlined').classes('w-32')
                    status = ui.select(STATUS_LABELS, label='상태', value=entry.status if entry else 'scheduled').props('outlined').classes('w-full')
                    message = ui.label().classes('text-sm text-red-700')
                    with ui.row().classes('w-full justify-end'):
                        cancel = ui.button('작성 닫기').props('flat')
                        save = ui.button('일정 저장', icon='save')
            fields = (target, title, day, start, duration, status)
            original = tuple(field.value for field in fields)
            saving = False

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
                    moment = datetime.combine(date.fromisoformat(day.value), parse_time(start.value), KST)
                    if not 2 <= moment.year <= 9998:
                        raise ValueError
                    value = CalendarEventInput(calendar_id=target.value, title=title.value, starts_at=moment,
                                               duration_minutes=duration.value, status=status.value)
                except (ValueError, TypeError):
                    message.text = '캘린더, 제목(1~200자), 날짜·시각, 시간(1~1440분 정수)을 확인해 주세요.'
                    return
                saving = True
                for field in (*fields, save, cancel):
                    field.disable()
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
