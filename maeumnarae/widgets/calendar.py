"""홈 월 달력과 선택일 일정."""
from datetime import datetime

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.calendar_repo import CalendarRepository
from maeumnarae.services.calendar_dates import visible_days, events_by_date, shift_month
from maeumnarae.services.calendar_holidays import korean_holidays
from maeumnarae.services.reporting import KST
from maeumnarae.services.school_calendar import load_school_events
from maeumnarae.views.calendar_event_editor import open_event_editor
from maeumnarae.views.calendar_view import event_caption, event_name, render_event_icons, show_school_event


class CalendarWidget:
    kind = 'calendar'
    title = '캘린더'
    icon = 'calendar_month'

    def __init__(self, home, teachers, instance_id=None, on_change=None, *,
                 on_calendar=None, on_open=None, on_open_linked=None):
        self.repository = CalendarRepository(home.database)
        self.on_calendar = on_calendar
        self.on_open = on_open
        self.on_open_linked = on_open_linked
        self.anchor = self.selected = self.today_date = datetime.now(KST).date()
        self.calendars = []
        self.events = {}
        self.holidays = {}
        self.loaded_revision = None
        self.request = 0
        self.loading = False
        self.editor_open = False

    def build_header_actions(self):
        ui.button('전체 캘린더', icon='open_in_new', on_click=self.on_calendar).props(
            'flat dense').classes('shrink-0').set_enabled(self.on_calendar is not None)
        ui.button(icon='refresh', on_click=self.reload).props(
            'flat round dense aria-label="캘린더 새로고침"').classes('shrink-0').tooltip('새로고침')

    def build(self):
        with ui.row().classes('w-full items-center gap-1'):
            ui.button(icon='chevron_left', on_click=lambda: self.shift(-1)).props('flat round dense aria-label="이전 달"')
            self.heading = ui.label().classes('font-bold')
            ui.button(icon='chevron_right', on_click=lambda: self.shift(1)).props('flat round dense aria-label="다음 달"')
            ui.button('오늘', on_click=self.today).props('flat dense')
            ui.space()
            self.add = ui.button('일정 추가', icon='add', on_click=lambda: self.edit()).props('flat dense')
            self.add.disable()
        self.message = ui.label().classes('text-xs')
        self.body = ui.column().classes('w-full gap-2')
        ui.timer(0, self.reload, once=True)
        ui.timer(0.5, self.refresh_if_changed)

    async def refresh_if_changed(self):
        if self.body.is_deleted or self.loading or self.editor_open:
            return
        if (self.loaded_revision != self.repository.database.write_revision
                or self.today_date != datetime.now(KST).date()):
            await self.reload()

    async def today(self):
        self.anchor = self.selected = datetime.now(KST).date()
        await self.reload()

    async def shift(self, direction):
        self.anchor = self.selected = shift_month(self.selected, direction)
        await self.reload()

    async def choose(self, day):
        self.selected = day
        if (day.year, day.month) != (self.anchor.year, self.anchor.month):
            self.anchor = day
            await self.reload()
        else:
            self.render()

    async def reload(self):
        if self.body.is_deleted:
            return
        self.request += 1
        request = self.request
        self.loading = True
        revision = self.repository.database.write_revision
        days = visible_days(self.anchor, 'month')
        self.message.text = '일정을 불러오는 중입니다…'
        self.add.disable()
        try:
            def load():
                calendars = self.repository.list()
                ids = [item.id for item in calendars if item.visible and item.source != 'holidays']
                events = self.repository.events(days[0], days[-1], ids)
                holidays = korean_holidays(days[0], days[-1]) if any(
                    item.visible and item.source == 'holidays' for item in calendars) else {}
                school_events, school_message = load_school_events(self.repository.database, calendars, days[0], days[-1])
                events.extend(school_events)
                return calendars, events, holidays, school_message

            calendars, events, holidays, school_message = await run.io_bound(load)
            if request != self.request or self.body.is_deleted:
                return
            self.calendars = calendars
            self.events = events_by_date(events, days)
            self.holidays = holidays
            self.loaded_revision = revision
            self.today_date = datetime.now(KST).date()
            self.add.set_enabled(any(item.source == 'custom' for item in calendars))
            self.message.text = ('' if any(item.visible for item in calendars) else
                                 '전체 캘린더에서 표시할 캘린더를 선택해 주세요.')
            if not any(item.source == 'custom' for item in calendars):
                self.message.text += ' 전체 캘린더에서 일정 등록용 캘린더를 추가해 주세요.'
            if school_message:
                self.message.text += ' ' + school_message
            self.render()
        except DatabaseError as error:
            if request == self.request and not self.body.is_deleted:
                self.body.clear()
                self.message.text = f'{error} · 새로고침을 눌러 다시 시도해 주세요.'
                # Avoid repeatedly retrying a failing database every half second.
                self.loaded_revision = revision
        finally:
            if request == self.request:
                self.loading = False

    def render(self):
        if self.body.is_deleted:
            return
        self.heading.text = f'{self.anchor:%Y년 %m월}'
        self.body.clear()
        with self.body:
            with ui.element('div').classes('w-full grid grid-cols-7 gap-1'):
                for label in '일월화수목금토':
                    ui.label(label).classes('text-center text-xs')
                for day in visible_days(self.anchor, 'month'):
                    classes = 'w-full min-w-0 p-0 rounded-lg '
                    if day == self.selected:
                        classes += 'app-primary-soft text-primary '
                    if day == self.today_date:
                        classes += 'ring-2 ring-inset app-primary-ring '
                    if day.month != self.anchor.month:
                        classes += 'opacity-50 '
                    with ui.button(on_click=lambda day=day: self.choose(day)).props(
                            f'flat dense no-caps aria-label="{day.isoformat()}" aria-pressed={str(day == self.selected).lower()}').classes(classes):
                        with ui.column().classes('items-center gap-0 w-full'):
                            color = ('text-red-600 dark:text-red-400' if day.weekday() == 6 or day in self.holidays
                                     else 'text-blue-600 dark:text-blue-400' if day.weekday() == 5
                                     else 'text-slate-800 dark:text-slate-200')
                            ui.label(str(day.day)).classes(color)
                            with ui.row().classes('h-2 gap-1 justify-center'):
                                colors = list(dict.fromkeys(e.color for e in self.events.get(day, [])))[:3]
                                for color in colors:
                                    ui.element('span').classes('w-1 h-1 rounded-full').style(f'background:{color}')
            ui.label(f'{self.selected:%m월 %d일}').classes('font-semibold')
            if self.selected in self.holidays:
                ui.label(self.holidays[self.selected]).classes('text-sm text-red-600 dark:text-red-400')
            entries = sorted(self.events.get(self.selected, []), key=lambda e: (not e.all_day, e.starts_at, e.source, e.id))
            if not entries:
                ui.label('일정이 없습니다').classes('text-sm')
            for entry in entries:
                with ui.button(on_click=lambda entry=entry: self.open_event(entry)).props('flat no-caps align=left').classes(
                        'w-full min-w-0').style('color:#000000 !important' if not entry.all_day else ''):
                    with ui.row().classes('w-full items-center gap-1 flex-nowrap'):
                        ui.element('span').classes('w-2 h-2 rounded-full shrink-0').style(f'background:{entry.color}')
                        ui.label(event_caption(entry)).classes('truncate min-w-0').tooltip(event_name(entry))
                        render_event_icons(entry)

    async def open_event(self, entry):
        if entry.source == 'neis':
            show_school_event(entry)
        elif entry.source == 'custom':
            await self.edit(entry)
        elif entry.source == 'counseling' and self.on_open:
            await self.on_open(entry.id)
        elif self.on_open_linked:
            await self.on_open_linked(entry)

    async def edit(self, entry=None):
        if self.editor_open or self.loading or self.body.is_deleted:
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
