"""기간별 완료 상담 통계와 집계 보고서 다운로드."""

from datetime import date, datetime

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import CounselingReport
from maeumnarae.services.reporting import KST, STATUS_LABELS, date_bounds, report_csv, report_html
from maeumnarae.repositories.reporting_repo import ReportingRepository


class StatisticsView:
    """화면과 다운로드가 동일한 집계 결과를 사용하도록 스냅샷을 보존한다."""

    def __init__(self, repository: ReportingRepository):
        self.repository = repository
        self.report: CounselingReport | None = None
        self.request = 0

    def build(self) -> None:
        today = datetime.now(KST).date()
        with ui.column().classes('w-full max-w-7xl mx-auto gap-5 p-4 md:p-8'):
            ui.label('상담 통계').classes('text-3xl font-bold text-slate-800')
            ui.label('완료 상담의 학생 수·시간·유형별 현황을 살펴보세요.').classes('text-slate-500')
            with ui.card().classes('w-full rounded-2xl shadow-sm p-5'):
                with ui.row().classes('w-full items-end'):
                    self.start = ui.input('통계 시작일', value=str(today.replace(day=1))).props('type=date outlined')
                    self.end = ui.input('통계 종료일', value=str(today)).props('type=date outlined')
                    ui.button('통계 조회', icon='search', on_click=self.load)
                    self.csv_button = ui.button('CSV 내보내기', icon='download', on_click=lambda: self.export('csv')).props('outline')
                    self.html_button = ui.button('인쇄용 보고서', icon='print', on_click=lambda: self.export('html')).props('outline')
                self.message = ui.label().classes('text-sm text-slate-500')
                ui.label('종료일 포함 · 상담 시작일 기준(KST) · 유형/월/학년은 완료 상담 기준 · 학년은 현재 학생 정보 기준').classes('text-sm text-slate-500')
                ui.label('보고서에는 학생 이름·학번·상담 본문이 포함되지 않습니다. 인쇄용 HTML은 브라우저에서 열어 인쇄할 수 있습니다.').classes('text-sm text-slate-500')
            self.results = ui.column().classes('w-full gap-5')
        self.csv_button.disable()
        self.html_button.disable()
        self.start.on_value_change(self.invalidate)
        self.end.on_value_change(self.invalidate)
        ui.timer(0.01, self.load, once=True)

    def invalidate(self) -> None:
        """입력 기간이 바뀌면 이전 결과를 내보내지 못하게 한다."""
        self.request += 1
        self.report = None
        self.csv_button.disable()
        self.html_button.disable()
        self.results.clear()
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
        self.report = report
        self.message.text = f'조회 기간: {start} ~ {end} · 전체 {report.total}건'
        self.csv_button.enable()
        self.html_button.enable()
        with self.results:
            with ui.element('div').classes('grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 w-full'):
                for label, value in [('전체 일정', f'{report.total}건'), ('완료 상담', f'{report.completed}건'),
                                     ('상담 학생 (중복 제외)', f'{report.students}명'), ('완료 상담 시간', f'{report.minutes}분')]:
                    with ui.card().classes('p-5 rounded-2xl shadow-sm'):
                        ui.label(label).classes('text-slate-500')
                        ui.label(value).classes('text-3xl font-bold text-teal-800')
            if not report.completed:
                ui.label('선택 기간에 완료된 상담이 없습니다.').classes('text-slate-500')
            with ui.row().classes('w-full items-start gap-4'):
                for title, buckets in [('상태별 전체 일정', report.statuses), ('유형별 완료 상담', report.categories),
                                       ('월별 완료 상담', report.months), ('현재 학년별 완료 상담', report.grades)]:
                    with ui.card().classes('w-full lg:w-[48%] p-5 rounded-2xl shadow-sm'):
                        ui.label(title).classes('text-lg font-bold')
                        labels = [STATUS_LABELS.get(b.label, b.label) if title == '상태별 전체 일정' else b.label for b in buckets]
                        if buckets:
                            ui.echart({'animation': False, 'xAxis': {'type': 'category', 'data': labels, 'axisLabel': {'interval': 0, 'width': 90, 'overflow': 'truncate'}},
                                'yAxis': {'type': 'value', 'minInterval': 1},
                                'grid': {'left': 45, 'right': 15, 'bottom': 60},
                                'series': [{'type': 'bar', 'data': [b.count for b in buckets], 'itemStyle': {'color': '#24756b'}}],
                                'dataZoom': [{'type': 'inside'}]}).classes('w-full h-64')
                        ui.table(columns=[dict(name='label', label='구분', field='label', align='left'),
                                          dict(name='count', label='건수', field='count')],
                                 rows=[dict(label=label, count=b.count) for label, b in zip(labels, buckets)],
                                 row_key='label', pagination=10).classes('w-full').props('flat')

    def export(self, kind: str) -> None:
        """화면에 표시된 보고서만 내보낸다. 파일은 서버 디스크에 남기지 않는다."""
        if self.report is None:
            return
        name = f'마음나래_상담통계_{self.report.start}_{self.report.end}'
        if kind == 'csv':
            ui.download.content(report_csv(self.report), name + '.csv', media_type='text/csv')
        else:
            ui.download.content(report_html(self.report), name + '.html', media_type='text/html')
