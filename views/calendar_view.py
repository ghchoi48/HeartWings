"""월간/주간 캘린더와 선택 날짜의 상담 일정."""

import calendar
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta

from nicegui import run, ui

from database import DatabaseError
from reporting import KST, STATUS_LABELS
from repositories.reporting_repo import ReportingRepository


def visible_days(anchor: date, mode: str) -> list[date]:
    """월요일 시작의 달력 날짜를 계산한다. 월간은 인접 월 날짜도 포함한다."""
    if mode == 'week':
        monday = anchor - timedelta(days=anchor.weekday())
        return [monday + timedelta(days=i) for i in range(7)]
    return [day for week in calendar.Calendar(firstweekday=0).monthdatescalendar(anchor.year, anchor.month) for day in week]


class CalendarView:
    """캘린더는 조회만 수행하고 일정 수정은 기존 상담 편집기로 위임한다."""

    def __init__(self, repository: ReportingRepository, on_open: Callable[[int], Awaitable[None]]):
        self.repository = repository
        self.on_open = on_open
        self.anchor = datetime.now(KST).date()
        self.selected = self.anchor
        self.count_request = 0
        self.day_request = 0
        self.offset = 0

    def build(self) -> None:
        with ui.column().classes('w-full max-w-7xl mx-auto gap-5 p-4 md:p-8'):
            ui.label('상담 캘린더').classes('text-3xl font-bold text-slate-800')
            ui.label('상담 시작일 기준 · 한국 표준시 · 날짜를 선택하면 상세 일정이 표시됩니다.').classes('text-slate-500')
            with ui.card().classes('w-full rounded-2xl p-5 shadow-sm'):
                with ui.row().classes('w-full items-center'):
                    ui.button('이전 기간', icon='chevron_left', on_click=lambda: self.shift(-1)).props('flat')
                    self.heading = ui.label().classes('text-xl font-bold')
                    ui.button('다음 기간', icon='chevron_right', on_click=lambda: self.shift(1)).props('flat')
                    ui.button('오늘', on_click=self.today).props('outline')
                    self.mode = ui.toggle({'month': '월간', 'week': '주간'}, value='month', on_change=self.change_mode)
                    self.status = ui.select({'all': '전체 상태', **STATUS_LABELS}, value='all', label='일정 상태', on_change=self.change_status).classes('w-36')
                with ui.row().classes('items-end'):
                    self.date_input = ui.input('기준 날짜', value=str(self.anchor)).props('type=date outlined')
                    ui.button('날짜로 이동', on_click=self.jump).props('flat')
                    ui.button('캘린더 새로고침', icon='refresh', on_click=self.reload).props('flat')
                self.message = ui.label().classes('text-sm text-slate-500')
                with ui.element('div').classes('w-full overflow-x-auto'):
                    self.grid = ui.column().classes('w-full gap-0').style('min-width:650px')
            with ui.card().classes('w-full rounded-2xl p-5 shadow-sm'):
                self.day_heading = ui.label().classes('text-xl font-bold')
                self.items = ui.column().classes('w-full')
                self.day_message = ui.label().classes('text-sm text-slate-500')
                with ui.row().classes('w-full justify-end items-center'):
                    self.previous = ui.button('일정 이전', on_click=lambda: self.page(-1)).props('flat')
                    self.page_label = ui.label()
                    self.next = ui.button('일정 다음', on_click=lambda: self.page(1)).props('flat')
        ui.timer(0.01, self.reload, once=True)

    async def change_mode(self) -> None:
        """선택 날짜를 기준으로 월간/주간 범위를 전환한다."""
        self.anchor = self.selected
        self.offset = 0
        await self.reload()

    async def change_status(self) -> None:
        """상태 필터 변경 시 상세 목록의 첫 페이지로 돌아간다."""
        self.offset = 0
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
        self.offset = 0
        await self.reload()

    async def today(self) -> None:
        self.anchor = self.selected = datetime.now(KST).date()
        self.offset = 0
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
        self.offset = 0
        await self.reload()

    async def reload(self) -> None:
        """달력과 선택 날짜를 갱신한다. 늦게 완료된 이전 요청은 폐기한다."""
        self.count_request += 1
        request = self.count_request
        self.day_request += 1
        days = visible_days(self.anchor, self.mode.value)
        self.date_input.value = str(self.anchor)
        self.heading.text = f'{self.anchor:%Y년 %m월}' if self.mode.value == 'month' else f'{days[0]:%Y.%m.%d} ~ {days[-1]:%m.%d}'
        self.grid.clear()
        self.items.clear()
        self.previous.disable()
        self.next.disable()
        self.message.text = '일정을 불러오는 중입니다…'
        self.day_message.text = ''
        try:
            counts = await run.io_bound(self.repository.daily_counts, days[0], days[-1],
                                        None if self.status.value == 'all' else self.status.value)
        except DatabaseError as error:
            if request == self.count_request:
                self.message.text = str(error)
            return
        if request != self.count_request:
            return
        with self.grid:
            with ui.element('div').classes('grid grid-cols-7 w-full'):
                for label in ['월', '화', '수', '목', '금', '토', '일']:
                    ui.label(label).classes('text-center p-2 bg-slate-50 font-semibold')
                for day in days:
                    color = 'bg-teal-50' if day == self.selected else 'bg-white'
                    with ui.column().classes(f'border border-slate-200 p-2 gap-1 min-h-24 {color}'):
                        ui.button(f'{day.month}/{day.day}', on_click=lambda day=day: self.choose(day)).props('flat dense').classes('w-full')
                        ui.label(f'{counts.get(day, 0)}건').classes('text-center w-full text-sm text-slate-500')
        self.message.text = f'표시 기간 일정 {sum(counts.values())}건'
        await self.load_day()

    async def choose(self, day: date) -> None:
        self.selected = day
        self.offset = 0
        await self.reload()

    async def page(self, direction: int) -> None:
        self.offset = max(0, self.offset + direction * 20)
        await self.load_day()

    async def load_day(self) -> None:
        """하루 일정 20개씩 조회하여 잘림 없이 탐색할 수 있게 한다."""
        self.day_request += 1
        request = self.day_request
        self.items.clear()
        self.previous.disable()
        self.next.disable()
        self.day_heading.text = f'{self.selected:%Y.%m.%d} 일정'
        self.day_message.text = '일정을 불러오는 중입니다…'
        try:
            items = await run.io_bound(self.repository.day_items, self.selected,
                status=None if self.status.value == 'all' else self.status.value, limit=21, offset=self.offset)
        except DatabaseError as error:
            if request == self.day_request:
                self.day_message.text = str(error)
            return
        if request != self.day_request:
            return
        with self.items:
            for item in items[:20]:
                with ui.row().classes('w-full items-center justify-between border rounded-xl p-3'):
                    with ui.column().classes('gap-1'):
                        ui.label(f'{item.starts_at.astimezone(KST):%H:%M} · {item.student_name} · {item.title}').classes('font-semibold')
                        ui.label(f'{STATUS_LABELS[item.status]} · {item.duration_minutes}분').classes('text-sm text-slate-500')
                    ui.button('일지 열기', on_click=lambda entry_id=item.id: self.on_open(entry_id)).props('outline')
        self.day_message.text = f'이 페이지에 {min(len(items), 20)}건' if items else '선택한 날짜와 상태에 해당하는 일정이 없습니다.'
        self.page_label.text = f'{self.offset // 20 + 1} 페이지'
        self.previous.set_enabled(self.offset > 0)
        self.next.set_enabled(len(items) > 20)
