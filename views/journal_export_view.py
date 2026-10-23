"""일지 업로드용 XLSX 생성, 누락 항목 확인 및 다운로드."""
from datetime import date, datetime

from nicegui import run, ui

from database import DatabaseError
from reporting import KST
from services.journal_export import ExportOptions, METHODS, XLSX_MIME, export_journals


class JournalExportView:
    def __init__(self, database):
        self.database = database
        self.busy = False
        self.result = None

    def build(self):
        today = datetime.now(KST).date()
        with ui.card().classes('w-full rounded-2xl shadow-sm p-5 gap-3'):
            ui.label('일지 엑셀 내보내기').classes('text-xl font-bold')
            ui.label('개인상담·집단상담·특별교육·자문·심리검사·교육/행사를 상담관리 업로드 서식으로 내보냅니다.').classes('text-slate-600')
            with ui.row().classes('w-full items-end'):
                self.all_dates = ui.checkbox('전체 기간', value=True)
                self.start = ui.date_input('일지 시작일', value=str(today.replace(month=3, day=1) if today.month >= 3 else date(today.year - 1, 3, 1))).props('outlined')
                self.end = ui.date_input('일지 종료일', value=str(today)).props('outlined')
                self.status = ui.select({'all': '모든 상태(예약·취소 포함)', 'completed': '완료만'},
                                        value='all', label='내보낼 일지 상태').props('outlined')
                self.wee = ui.select(['Wee클래스', '일반'], value='Wee클래스', label='Wee클래스 구분').props('outlined')
                self.method = ui.select(list(METHODS), value='면담', label='기록에 없는 상담매체').props('outlined')
            ui.label('학년도는 일지 날짜의 3월~다음 해 2월 기준입니다. 상담분류는 전문상담, 상담사소속은 전문상담교사로 입력합니다.').classes('text-sm text-slate-500')
            ui.label('상담제목·상담내용은 상담구분과 동일하게 입력합니다. 실제 제목·본문·비밀 메모·이름·연락처는 포함하지 않습니다.').classes('text-sm text-slate-500')
            ui.label('특별교육은 개인상담으로 분류합니다. 학년은 해당 학년도 학적, 집단 인원·학년·성별은 현재 연결된 참여 학생 기준입니다. 상태가 없는 심리검사·교육/행사는 완료만 선택해도 포함됩니다.').classes('text-sm text-slate-500')
            with ui.row():
                self.prepare = ui.button('일지 XLSX 만들기', icon='table_view', on_click=self.generate)
                self.download_button = ui.button('XLSX 다운로드', icon='download', on_click=self.download).props('outline')
            self.message = ui.label().classes('text-sm text-slate-600')
            self.issues = ui.column().classes('w-full')
        self.controls = (self.all_dates, self.start, self.end, self.status, self.wee, self.method)
        for control in self.controls:
            control.on_value_change(self.invalidate)
        self.invalidate()

    def invalidate(self):
        self.result = None
        self.download_button.disable()
        self.issues.clear()
        self.message.text = ''
        self.start.set_enabled(not self.all_dates.value and not self.busy)
        self.end.set_enabled(not self.all_dates.value and not self.busy)

    async def generate(self):
        if self.busy:
            return
        self.invalidate()
        try:
            options = ExportOptions(
                start=None if self.all_dates.value else date.fromisoformat(self.start.value or ''),
                end=None if self.all_dates.value else date.fromisoformat(self.end.value or ''),
                wee_class=self.wee.value, status=self.status.value, default_method=self.method.value)
            options.validate()
        except (ValueError, TypeError):
            self.message.text = '내보낼 기간과 선택 항목을 확인해 주세요.'
            return
        self.busy = True
        for control in (*self.controls, self.prepare):
            control.disable()
        self.message.text = '모든 일지 기록을 읽고 엑셀 파일을 만드는 중입니다…'
        try:
            self.result = await run.io_bound(export_journals, self.database, options)
            counts = ' · '.join(f'{kind} {count}건' for kind, count in self.result.counts.items())
            self.message.text = f'전체 {self.result.count}건' + (f' · {counts}' if counts else ' · 내보낼 기록이 없습니다.')
            with self.issues:
                if self.result.issues:
                    ui.label(f'확인이 필요한 행 {len(self.result.issues)}개입니다. 빈 필수 항목은 다운로드한 엑셀에서 보완한 뒤 업로드해 주세요.').classes('text-amber-800')
                    ui.table(columns=[dict(name='issue', label='확인할 항목', field='issue', align='left')],
                             rows=[dict(id=index, issue=issue) for index, issue in enumerate(self.result.issues)],
                             row_key='id', pagination=10).classes('w-full').props('wrap-cells flat')
            self.download_button.enable()
        except (DatabaseError, OSError, ValueError) as error:
            self.result = None
            self.message.text = f'엑셀 파일을 만들지 못했습니다. {error}'
        finally:
            self.busy = False
            for control in (*self.controls, self.prepare):
                control.enable()
            self.start.set_enabled(not self.all_dates.value)
            self.end.set_enabled(not self.all_dates.value)

    def download(self):
        if self.result is None:
            return
        ui.download.content(self.result.content,
                            f'상담관리_업로드_{datetime.now(KST):%Y%m%d_%H%M%S}.xlsx', media_type=XLSX_MIME)
