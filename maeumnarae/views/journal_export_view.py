"""일지 업로드용 XLSX 생성, 누락 항목 확인 및 다운로드."""
from datetime import date, datetime, timedelta

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.journal_export_repo import JournalExportRepository
from maeumnarae.services.reporting import KST
from maeumnarae.services.journal_export import ExportOptions, XLSX_MIME, export_journals, export_ledger, school_year
from maeumnarae.views.settings_card import settings_card


class JournalExportView:
    def __init__(self, database, *, ledger=False):
        self.database = database
        self.ledger = ledger
        self.students_download_button = None
        self.busy = False
        self.result = None

    def build(self, *, collapsible: bool = False):
        today = datetime.now(KST).date()
        current_year = school_year(today)
        title = '내부결재용 상담 대장 내보내기' if self.ledger else 'NEIS 업로드용 파일 내보내기'
        description = ('학생 ID를 포함한 상담 대장과 연결된 학생 정보 파일을 각각 내보냅니다.' if self.ledger else
                       '개인상담·집단상담·특별교육·자문·심리검사·교육/행사를 상담관리 업로드 서식으로 내보냅니다.')
        with settings_card(title, 'file_download', description, collapsible=collapsible):
            with ui.row().classes('w-full items-end flex-nowrap overflow-x-auto'):
                self.period = ui.select({'year': '학년도', 'custom': '기간 직접 입력'},
                                        value='year', label='내보낼 기간').props('outlined').classes('flex-1 min-w-[200px]')
                self.year = ui.select({}, label='학년도', with_input=True).props('outlined').classes('flex-1 min-w-[200px]')
                self.year.bind_visibility_from(self.period, 'value', lambda value: value == 'year')
                self.start = ui.date_input('일지 시작일', value=str(date(current_year, 3, 1))).props('outlined').classes('flex-1 min-w-[200px]')
                self.end = ui.date_input('일지 종료일', value=str(today)).props('outlined').classes('flex-1 min-w-[200px]')
                self.start.bind_visibility_from(self.period, 'value', lambda value: value == 'custom')
                self.end.bind_visibility_from(self.period, 'value', lambda value: value == 'custom')
                self.status = ui.select({'completed': '완료만', 'completed_scheduled': '완료 및 예약'},
                                        value='completed', label='내보낼 일지 상태').props('outlined').classes('flex-1 min-w-[200px]')
            with ui.row():
                self.prepare = ui.button('상담 대장·학생 정보 만들기' if self.ledger else '일지 XLSX 만들기', icon='table_view', on_click=self.generate)
                self.download_button = ui.button('내부결재용 상담 대장 내보내기' if self.ledger else 'XLSX 다운로드', icon='download', on_click=self.download).props('outline')
                if self.ledger:
                    self.students_download_button = ui.button('Wee클래스 보관용 학생 정보 대장 내보내기', icon='download', on_click=self.download_students).props('outline')
            self.message = ui.label().classes('text-sm text-slate-600')
            self.issues = ui.column().classes('w-full')
        self.controls = (self.period, self.year, self.start, self.end, self.status)
        for control in self.controls:
            control.on_value_change(self.invalidate)
        self.invalidate()
        ui.timer(0.01, self.load_school_years, once=True)

    async def load_school_years(self):
        try:
            years = await run.io_bound(JournalExportRepository(self.database).school_years)
        except (DatabaseError, ValueError):
            self.message.text = '학년도 목록을 불러오지 못했습니다.'
            return
        current_year = school_year(datetime.now(KST).date())
        selected = current_year if current_year in years else (years[0] if years else None)
        self.year.set_options({year: f'{year}학년도' for year in years}, value=selected)
        self.update_period_controls()
        if not years:
            self.message.text = '내보낼 일지 기록이 없습니다.'

    def invalidate(self):
        self.result = None
        self.download_button.disable()
        if self.students_download_button is not None:
            self.students_download_button.disable()
        self.issues.clear()
        self.message.text = ''
        self.update_period_controls()

    def update_period_controls(self):
        self.year.set_enabled(self.period.value == 'year' and bool(self.year.options) and not self.busy)
        self.start.set_enabled(self.period.value == 'custom' and not self.busy)
        self.end.set_enabled(self.period.value == 'custom' and not self.busy)
        self.prepare.set_enabled(not self.busy and (self.period.value == 'custom' or self.year.value is not None))

    async def generate(self):
        if self.busy:
            return
        self.invalidate()
        try:
            if self.period.value == 'year':
                year = int(self.year.value)
                start = date(year, 3, 1)
                end = date(year + 1, 3, 1) - timedelta(days=1)
            else:
                start = date.fromisoformat(self.start.value or '')
                end = date.fromisoformat(self.end.value or '')
            options = ExportOptions(
                start=start, end=end,
                wee_class='Wee클래스', status=self.status.value)
            options.validate()
        except (ValueError, TypeError):
            self.message.text = '내보낼 기간과 선택 항목을 확인해 주세요.'
            return
        self.busy = True
        for control in (*self.controls, self.prepare):
            control.disable()
        self.message.text = '모든 일지 기록을 읽고 엑셀 파일을 만드는 중입니다…'
        try:
            self.result = await run.io_bound(export_ledger if self.ledger else export_journals, self.database, options)
            counts = ' · '.join(f'{kind} {count}건' for kind, count in self.result.counts.items())
            self.message.text = f'전체 {self.result.count}건' + (f' · {counts}' if counts else ' · 내보낼 기록이 없습니다.')
            if self.ledger:
                self.message.text += f' · 연결 학생 {self.result.student_count}명'
            with self.issues:
                if self.result.issues:
                    ui.label(f'확인이 필요한 행 {len(self.result.issues)}개입니다. 다운로드한 엑셀에서 해당 항목을 확인해 주세요.').classes('text-amber-800')
                    ui.table(columns=[dict(name='issue', label='확인할 항목', field='issue', align='left')],
                             rows=[dict(id=index, issue=issue) for index, issue in enumerate(self.result.issues)],
                             row_key='id', pagination=10).classes('w-full').props('wrap-cells flat')
            self.download_button.enable()
            if self.students_download_button is not None:
                self.students_download_button.enable()
        except (DatabaseError, OSError, ValueError) as error:
            self.result = None
            self.message.text = f'엑셀 파일을 만들지 못했습니다. {error}'
        finally:
            self.busy = False
            for control in (*self.controls, self.prepare):
                control.enable()
            self.update_period_controls()

    def download(self):
        if self.result is None:
            return
        prefix = '상담대장' if self.ledger else '상담관리_업로드'
        ui.download.content(self.result.content,
                            f'{prefix}_{datetime.now(KST):%Y%m%d_%H%M%S}.xlsx', media_type=XLSX_MIME)

    def download_students(self):
        if not self.ledger or self.result is None:
            return
        ui.download.content(self.result.students_content,
                            f'상담대장_학생정보_{datetime.now(KST):%Y%m%d_%H%M%S}.xlsx', media_type=XLSX_MIME)
