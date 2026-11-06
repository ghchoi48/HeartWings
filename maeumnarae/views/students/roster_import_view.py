"""XLSX 명부 서식 다운로드, 업로드 미리보기와 일괄 등록 컨트롤."""

from maeumnarae.core.secure_upload import SecureUpload

from nicegui import events, run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.students.roster_import_repo import RosterImportRepository
from maeumnarae.services.students.roster_import import COLUMNS, MAX_FILE_BYTES, TITLES, XLSX_MIME, import_template


class RosterImportView:
    def __init__(self, database, kind, is_busy, set_busy, on_imported):
        self.repository = RosterImportRepository(database)
        self.kind = kind
        self.is_busy = is_busy
        self.set_busy = set_busy
        self.on_imported = on_imported
        self.batch = None

    def build(self):
        title = TITLES[self.kind]
        with ui.card().classes('w-full min-w-0 shadow-none border border-slate-200 p-4 gap-3'):
            ui.label(f'{title} 일괄 등록').classes('text-lg font-bold text-slate-800')
            ui.label('서식을 내려받아 작성한 뒤 업로드하세요. 미리보기를 확인하고 등록할 수 있습니다.').classes('text-sm text-slate-500')
            self.download = ui.button(f'{title} 서식 다운로드', icon='download', on_click=self.download_template).props('outline')
            self.upload = SecureUpload(label=f'{title} XLSX 파일', auto_upload=True, max_files=1,
                                    max_file_size=MAX_FILE_BYTES, on_upload=self.receive,
                                    on_rejected=lambda: ui.notify('10MB 이하의 XLSX 파일 하나를 선택해 주세요.', type='warning')
                                    ).props('accept=.xlsx').classes('w-full')
            self.upload.on('removed', lambda: self.clear(False))
            self.status = ui.label().classes('text-sm text-primary')
        with ui.dialog().props('persistent') as self.dialog:
            with ui.card().classes('w-full max-w-4xl max-h-[85vh] p-6 gap-4'):
                ui.label(f'{title} 일괄 등록 미리보기').classes('text-xl font-bold')
                self.filename = ui.label().classes('text-sm text-slate-500 break-all')
                self.preview = ui.column().classes('w-full min-h-0 overflow-auto gap-2')
                with ui.row().classes('w-full justify-end gap-2 shrink-0'):
                    self.reset = ui.button('취소', on_click=self.clear).props('flat')
                    self.register = ui.button(f'{title} 등록', icon='person_add', on_click=self.save)
                self.register.disable()

    def apply_busy(self, value):
        for control in (self.download, self.upload, self.reset):
            control.set_enabled(not value)
        self.register.set_enabled(not value and self.batch is not None and not self.batch.errors)

    def clear(self, reset_upload=True):
        if self.is_busy():
            return
        self.batch = None
        self.preview.clear()
        self.register.disable()
        self.dialog.close()
        if reset_upload:
            self.upload.reset()

    async def download_template(self):
        if self.is_busy():
            return
        self.set_busy(True)
        self.download.props('loading')
        try:
            content = await run.io_bound(import_template, self.kind)
            ui.download.content(content, f'{TITLES[self.kind]}_일괄등록_서식.xlsx', media_type=XLSX_MIME)
        except (OSError, ValueError):
            ui.notify('서식 파일을 만들지 못했습니다. 다시 시도해 주세요.', type='negative')
        finally:
            self.download.props(remove='loading')
            self.set_busy(False)

    async def receive(self, event: events.UploadEventArguments):
        if self.is_busy():
            return
        self.clear(False)
        self.status.text = ''
        self.filename.text = event.file.name
        self.dialog.open()
        with self.preview:
            ui.label('파일을 검사하는 중입니다…').classes('text-sm text-slate-500')
        self.set_busy(True)
        try:
            if not event.file.name.lower().endswith('.xlsx'):
                raise ValueError('XLSX 서식 파일을 선택해 주세요.')
            content = await event.file.read()
            self.batch = await run.io_bound(self.repository.preview, content, self.kind)
            self.preview.clear()
            with self.preview:
                ui.label(f'등록 대상 {len(self.batch.rows):,}명 · 오류 {len(self.batch.errors):,}건').classes('font-semibold')
                if self.batch.errors:
                    ui.label('오류를 수정하고 파일을 다시 업로드해 주세요. 현재 파일은 등록되지 않습니다.').classes('text-sm text-red-700')
                    for error in self.batch.errors[:50]:
                        ui.label(error).classes('text-sm text-red-700 break-words')
                    if len(self.batch.errors) > 50:
                        ui.label(f'오류 중 50건을 표시했습니다. 전체 오류 {len(self.batch.errors):,}건').classes('text-sm text-red-700')
                keys = ['name', 'school_year', 'grade', 'classroom', 'student_number'] if self.kind == 'students' else [key for key, _, _ in COLUMNS[self.kind]]
                columns = [{'name': key, 'field': key, 'label': label, 'align': 'left'}
                           for key, label, _ in COLUMNS[self.kind] if key in keys]
                rows = [dict(row.value.model_dump(mode='json'), _row=row.number) for row in self.batch.rows[:20]]
                ui.table(columns=[{'name': '_row', 'field': '_row', 'label': '파일 행', 'align': 'left'}, *columns],
                         rows=rows, row_key='_row').props('flat dense').classes('w-full')
                ui.label('미리보기는 최대 20명입니다. 등록하면 파일의 모든 대상이 새로 추가됩니다.').classes('text-sm text-slate-500')
        except (DatabaseError, ValueError, OSError) as error:
            self.batch = None
            self.preview.clear()
            with self.preview:
                ui.label(str(error)).classes('text-sm text-red-700 break-words')
        finally:
            self.set_busy(False)

    async def save(self):
        if self.is_busy() or self.batch is None or self.batch.errors:
            return
        self.set_busy(True)
        self.register.props('loading')
        succeeded = False
        try:
            count = await run.io_bound(self.repository.save, self.batch)
            self.batch = None  # 같은 파일이 등록 버튼 연타로 재등록되지 않게 한다.
            self.preview.clear()
            self.dialog.close()
            self.status.text = f'{TITLES[self.kind]} {count:,}명을 등록했습니다.'
            self.upload.reset()
            ui.notify(f'{TITLES[self.kind]} {count:,}명을 등록했습니다.', type='positive')
            succeeded = True
        except (DatabaseError, ValueError) as error:
            with self.preview:
                ui.label(str(error)).classes('text-sm text-red-700 whitespace-pre-wrap')
            # 저장 시 중복이 추가되었거나 DB가 잠겼다면 파일을 다시 검사해야 한다.
            self.batch = None
        finally:
            self.register.props(remove='loading')
            self.set_busy(False)
        if succeeded:
            await self.on_imported(self.kind)
