"""기간별 완료 상담 통계 조회."""

from calendar import monthrange
from datetime import date, datetime, timedelta

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.services.reports.reporting import KST, date_bounds
from maeumnarae.repositories.reports.reporting_repo import ReportingRepository
from maeumnarae.views.settings.display_settings import DEFAULT_PRIMARY, DisplaySettings


class StatisticsView:
    """선택한 기간의 상담 집계 결과를 표시한다."""

    def __init__(self, repository: ReportingRepository, display: DisplaySettings | None = None):
        self.repository = repository
        self.request = 0
        self.reload_timer = None
        self.setting_period = False
        self.area_kind = '개인상담'
        self.primary = display.values['primary'] if display else DEFAULT_PRIMARY
        self.charts: list[ui.echart] = []
        if display:
            display.primary_listeners.append(self.update_primary)

    def update_primary(self, color: str) -> None:
        self.primary = color
        for chart in self.charts:
            if not chart.is_deleted:
                for series in chart.options['series']:
                    series['itemStyle']['color'] = color
                chart.update()

    def build(self) -> None:
        today = datetime.now(KST).date()
        with ui.column().classes('w-full max-w-7xl mx-auto gap-5 p-4 md:p-8'):
            ui.label('상담 통계').classes('text-3xl font-bold text-slate-800')
            ui.label('완료 상담의 학생 수·시간·유형별 현황을 살펴보세요.').classes('text-slate-500')
            with ui.card().classes('w-full rounded-2xl shadow-sm p-5'):
                with ui.row().classes('w-full items-end'):
                    self.start = ui.date_input('통계 시작일', value=str(today.replace(day=1))).props('outlined')
                    self.end = ui.date_input('통계 종료일', value=str(today)).props('outlined')
                with ui.row().classes('w-full gap-2'):
                    for label, period in [('학년도', 'school_year'), ('지난달', 'last_month'),
                                          ('이번 달', 'this_month'), ('오늘', 'today')]:
                        ui.button(label, on_click=lambda _, period=period: self.set_period(period)).props(
                            'outline dense no-caps').style(
                            'width: 56px; height: 18px; min-height: 18px; padding: 0; font-size: 10px; line-height: 1;')
                self.message = ui.label().classes('text-sm text-slate-500')
                ui.label('종료일 포함 · 한국 시간 기준 · 유형/월/학년/분야는 완료 일지 기준').classes('text-sm text-slate-500')
                ui.label('심리검사·교육/행사는 등록 건을 집계합니다. 학년은 현재 학생 정보 기준이며, 집단상담은 출석 학생의 학년별로 회기당 1건을 집계합니다.').classes('text-xs text-slate-500')
            self.results = ui.column().classes('w-full gap-5')
        self.start.on_value_change(self.period_changed)
        self.end.on_value_change(self.period_changed)
        self.reload_timer = ui.timer(0.01, self.load, once=True)

    def set_period(self, period: str) -> None:
        """한국 시간의 오늘을 기준으로 조회 기간을 입력한다."""
        today = datetime.now(KST).date()
        if period == 'school_year':
            year = today.year if today.month >= 3 else today.year - 1
            start = date(year, 3, 1)
            end = date(year + 1, 3, 1) - timedelta(days=1)
        elif period == 'last_month':
            end = today.replace(day=1) - timedelta(days=1)
            start = end.replace(day=1)
        elif period == 'this_month':
            start = today.replace(day=1)
            end = today.replace(day=monthrange(today.year, today.month)[1])
        else:
            start = end = today
        self.setting_period = True
        try:
            self.start.set_value(start.isoformat())
            self.end.set_value(end.isoformat())
        finally:
            self.setting_period = False
        self.period_changed()

    def period_changed(self) -> None:
        """연속 입력을 모아 마지막으로 지정한 기간을 자동 조회한다."""
        if self.setting_period:
            return
        self.invalidate()
        if self.reload_timer is not None:
            self.reload_timer.deactivate()
        self.reload_timer = ui.timer(0.2, self.load, once=True)

    def invalidate(self) -> None:
        """입력 기간이 바뀌면 이전 결과와 진행 중인 조회를 무효화한다."""
        self.request += 1
        self.results.clear()
        self.charts.clear()
        self.message.text = ''

    async def load(self) -> None:
        """전체 기간을 SQL에서 집계하며 페이지 제한으로 잘라 집계하지 않는다."""
        self.invalidate()
        request = self.request
        try:
            start, end = date.fromisoformat(self.start.value or ''), date.fromisoformat(self.end.value or '')
            date_bounds(start, end)
        except ValueError as error:
            self.message.text = '시작일과 종료일을 확인해 주세요. ' + str(error)
            return
        self.message.text = '통계를 집계하는 중입니다…'
        try:
            report = await run.io_bound(self.repository.statistics, start, end)
        except DatabaseError as error:
            if request == self.request:
                self.message.text = str(error)
            return
        if request != self.request:
            return
        self.message.text = f'조회 기간: {start} ~ {end} · 전체 {report.total}건'
        with self.results:
            with ui.element('div').classes('grid grid-cols-1 md:grid-cols-2 xl:grid-cols-12 gap-4 w-full items-stretch'):
                for label, value, icon in [
                    ('전체 일정', f'{report.total}건', 'event_note'),
                    ('완료 상담', f'{report.completed}건', 'task_alt'),
                    ('상담 학생 (중복 제외)', f'{report.students}명', 'groups'),
                    ('완료 상담 시간', f'{report.minutes:,}분', 'schedule'),
                ]:
                    with ui.card().classes('min-w-0 p-5 rounded-2xl shadow-sm xl:col-span-3 gap-3'):
                        with ui.row().classes('w-full items-center justify-between'):
                            ui.label(label).classes('text-sm text-slate-500')
                            ui.icon(icon).classes('text-primary text-xl')
                        ui.label(value).classes('text-3xl font-bold text-primary')
                for title, buckets, span in [
                    ('유형별 상담 건수', report.categories, 'md:col-span-2 xl:col-span-12'),
                    ('월별 상담 건수', report.months, 'xl:col-span-8'),
                    ('학년별 상담 건수', report.grades, 'xl:col-span-4'),
                ]:
                    with ui.card().classes(f'min-w-0 w-full p-5 rounded-2xl shadow-sm gap-3 {span}'):
                        ui.label(title).classes('text-lg font-bold')
                        self.render_buckets(buckets, horizontal=title == '유형별 상담 건수')
                with ui.card().classes('min-w-0 w-full p-5 rounded-2xl shadow-sm gap-3 md:col-span-2 xl:col-span-12'):
                    with ui.row().classes('w-full items-center justify-between flex-nowrap gap-3'):
                        ui.label('상담 분야별 상담 건수').classes('text-base md:text-lg font-bold min-w-0')
                        selector = ui.select(['개인상담', '학부모상담', '집단상담', '자문'],
                                             value=self.area_kind, label='상담 유형').props('outlined dense').classes('w-32 shrink-0')
                    area_body = ui.column().classes('w-full min-w-0 gap-3')
                    areas = dict(report.areas)

                    def render_areas():
                        self.area_kind = selector.value
                        area_body.clear()
                        self.charts = [chart for chart in self.charts if not chart.is_deleted]
                        with area_body:
                            self.render_buckets(areas.get(self.area_kind, ()), horizontal=True)

                    selector.on_value_change(render_areas)
                    render_areas()

    def render_buckets(self, buckets, *, horizontal=False):
        """벤토 카드의 집계 차트 또는 빈 결과 안내를 표시한다."""
        labels = [b.label for b in buckets]
        if any(bucket.count for bucket in buckets):
            chart = ui.echart({
                'animation': False,
                'tooltip': {'trigger': 'axis', 'axisPointer': {'type': 'shadow'}},
                'xAxis': {'type': 'value', 'minInterval': 1} if horizontal else {
                    'type': 'category', 'data': labels, 'axisLabel': {'hideOverlap': True}},
                'yAxis': {'type': 'category', 'data': labels, 'inverse': True,
                          'axisLabel': {'width': 110, 'overflow': 'truncate'}} if horizontal else {
                    'type': 'value', 'minInterval': 1},
                'grid': {'left': 12, 'right': 12, 'top': 20, 'bottom': 20, 'containLabel': True},
                'series': [{'type': 'bar', 'barMaxWidth': 48, 'data': [b.count for b in buckets],
                            'itemStyle': {'color': self.primary,
                                          'borderRadius': [0, 6, 6, 0] if horizontal else [6, 6, 0, 0]}}],
            }).classes('w-full').style(f'height: {max(256, len(buckets) * 34) if horizontal else 256}px')
            self.charts.append(chart)
        else:
            with ui.column().classes('w-full h-64 items-center justify-center gap-2'):
                ui.icon('bar_chart', size='36px').classes('text-slate-400')
                ui.label('선택 기간에 집계된 내역이 없습니다.').classes('text-sm text-slate-500')
