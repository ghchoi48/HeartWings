"""기간별 완료 상담 통계 조회."""

from calendar import monthrange
from datetime import date, datetime, timedelta

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.services.reports.reporting import KST, STATUS_LABELS, date_bounds
from maeumnarae.repositories.reports.reporting_repo import ReportingRepository
from maeumnarae.views.settings.display_settings import DEFAULT_PRIMARY, DisplaySettings


class StatisticsView:
    """선택한 기간의 상담 집계 결과를 표시한다."""

    def __init__(self, repository: ReportingRepository, display: DisplaySettings | None = None):
        self.repository = repository
        self.request = 0
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
                    ui.button('통계 조회', icon='search', on_click=self.load)
                with ui.row().classes('w-full gap-2'):
                    for label, period in [('학년도', 'school_year'), ('지난달', 'last_month'),
                                          ('이번 달', 'this_month'), ('오늘', 'today')]:
                        ui.button(label, on_click=lambda _, period=period: self.set_period(period)).props(
                            'outline dense no-caps').style(
                            'width: 56px; height: 18px; min-height: 18px; padding: 0; font-size: 10px; line-height: 1;')
                self.message = ui.label().classes('text-sm text-slate-500')
                ui.label('종료일 포함 · 상담 시작일 기준(KST) · 유형/월/학년은 완료 상담 기준 · 학년은 현재 학생 정보 기준').classes('text-sm text-slate-500')
            self.results = ui.column().classes('w-full gap-5')
        self.start.on_value_change(self.invalidate)
        self.end.on_value_change(self.invalidate)
        ui.timer(0.01, self.load, once=True)

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
        self.start.set_value(start.isoformat())
        self.end.set_value(end.isoformat())

    def invalidate(self) -> None:
        """입력 기간이 바뀌면 이전 결과와 진행 중인 조회를 무효화한다."""
        self.request += 1
        self.results.clear()
        self.charts.clear()
        self.message.text = '기간이 변경되었습니다. 통계 조회를 눌러 주세요.'

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
            with ui.element('div').classes('grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 w-full'):
                for label, value in [('전체 일정', f'{report.total}건'), ('완료 상담', f'{report.completed}건'),
                                     ('상담 학생 (중복 제외)', f'{report.students}명'), ('완료 상담 시간', f'{report.minutes}분')]:
                    with ui.card().classes('p-5 rounded-2xl shadow-sm'):
                        ui.label(label).classes('text-slate-500')
                        ui.label(value).classes('text-3xl font-bold text-primary')
            if not report.completed:
                ui.label('선택 기간에 완료된 상담이 없습니다.').classes('text-slate-500')
            with ui.row().classes('w-full items-start gap-4'):
                for title, buckets in [('상태별 전체 일정', report.statuses), ('유형별 완료 상담', report.categories),
                                       ('월별 완료 상담', report.months), ('현재 학년별 완료 상담', report.grades)]:
                    with ui.card().classes('w-full lg:w-[48%] p-5 rounded-2xl shadow-sm'):
                        ui.label(title).classes('text-lg font-bold')
                        labels = [STATUS_LABELS.get(b.label, b.label) if title == '상태별 전체 일정' else b.label for b in buckets]
                        if buckets:
                            chart = ui.echart({'animation': False, 'xAxis': {'type': 'category', 'data': labels, 'axisLabel': {'interval': 0, 'width': 90, 'overflow': 'truncate'}},
                                'yAxis': {'type': 'value', 'minInterval': 1},
                                'grid': {'left': 45, 'right': 15, 'bottom': 60},
                                'series': [{'type': 'bar', 'data': [b.count for b in buckets], 'itemStyle': {'color': self.primary}}],
                                'dataZoom': [{'type': 'inside'}]}).classes('w-full h-64')
                            self.charts.append(chart)
                        ui.table(columns=[dict(name='label', label='구분', field='label', align='left'),
                                          dict(name='count', label='건수', field='count')],
                                 rows=[dict(label=label, count=b.count) for label, b in zip(labels, buckets)],
                                 row_key='label', pagination=10).classes('w-full').props('flat')
