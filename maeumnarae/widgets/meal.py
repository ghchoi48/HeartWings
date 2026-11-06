"""학교 설정을 이용하는 날짜별 나이스 급식 위젯."""

from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.settings.school_settings_repo import SchoolSettingsRepository
from maeumnarae.services.school.neis import MEALS, SOURCE_URL, NeisError, fetch_meals, text_lines


class Meal:
    kind = 'meal'
    title = '급식'
    icon = 'restaurant'
    default_height = 520

    def __init__(self, home, teachers, instance_id=None, on_change=None):
        self.school = SchoolSettingsRepository(home.database)
        self.day = datetime.now(timezone(timedelta(hours=9))).date()
        self.meal = '2'
        self.generation = 0

    def build_header_actions(self):
        ui.button(icon='refresh', on_click=self.reload).props(
            'flat round dense aria-label="급식 새로고침"').classes('shrink-0').tooltip('새로고침')

    def build(self):
        with ui.row().classes('w-full items-center justify-between flex-nowrap gap-1'):
            ui.button(icon='chevron_left', on_click=lambda: self.move(-1)).props('flat round aria-label="이전 날짜 급식"')
            self.date_label = ui.label().classes('font-semibold text-slate-700')
            ui.button(icon='chevron_right', on_click=lambda: self.move(1)).props('flat round aria-label="다음 날짜 급식"')
        with ui.row().classes('w-full items-center gap-2'):
            ui.select(MEALS, value='2', label='식사 구분', on_change=self.select).props('outlined dense').classes('flex-1')
            ui.button('오늘', on_click=self.today).props('flat dense')
        self.results = ui.column().classes('w-full gap-2')
        ui.link('출처: 나이스 교육정보 개방 포털', SOURCE_URL, new_tab=True).classes('text-xs text-slate-400')
        ui.timer(0, self.reload, once=True)

    async def move(self, delta):
        self.day += timedelta(days=delta)
        await self.reload()

    async def today(self):
        self.day = datetime.now(timezone(timedelta(hours=9))).date()
        await self.reload()

    async def select(self, event):
        self.meal = event.value
        await self.reload()

    async def reload(self):
        if self.results.is_deleted:
            return
        self.generation += 1
        generation = self.generation
        day, meal = self.day, self.meal
        self.date_label.text = f'{day:%Y.%m.%d} ({"월화수목금토일"[day.weekday()]})'
        self.results.clear()
        with self.results:
            ui.label('급식 정보를 불러오는 중입니다…').classes('text-sm text-slate-400')
        try:
            settings = await run.io_bound(self.school.get)
            if generation != self.generation or self.results.is_deleted:
                return
            rows = await run.io_bound(fetch_meals, settings.neis_office_code,
                                      settings.neis_school_code, day, meal, settings.neis_api_key)
        except (DatabaseError, NeisError) as error:
            if generation != self.generation or self.results.is_deleted:
                return
            self.results.clear()
            with self.results:
                ui.label(str(error)).classes('text-sm text-slate-500')
            return
        if generation != self.generation or self.results.is_deleted:
            return
        self.results.clear()
        with self.results:
            if not rows:
                ui.label(f'{day:%m월 %d일} {MEALS[meal]} 급식 정보가 없습니다.').classes('text-sm text-slate-500')
            for row in rows:
                ui.label(row.get('SCHUL_NM') or settings.school_name).classes('text-sm text-primary font-semibold')
                for dish in text_lines(row.get('DDISH_NM', '')):
                    ui.label(dish).classes('text-sm text-slate-700 break-words')
                if row.get('CAL_INFO'):
                    ui.label(row['CAL_INFO']).classes('text-xs text-slate-500')
            if rows:
                ui.label('메뉴 옆 숫자는 나이스 알레르기 식재료 번호입니다.').classes('text-xs text-slate-400')
