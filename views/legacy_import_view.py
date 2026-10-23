"""XLSB 이관 옵션, 미리보기 및 명시적 저장."""

from nicegui import run, ui
import re

from database import DatabaseError
from models import StudentInput, TeacherInput, ConsultationInput, CounselingInput, PsychologicalTestInput, current_school_year
from repositories.legacy_import_repo import LegacyImportRepository
from services.legacy_import import MAX_BYTES, read_rows, period_key


class LegacyImportView:
    def __init__(self, database, is_busy, set_busy, on_imported):
        self.repository = LegacyImportRepository(database)
        self.is_busy, self.set_busy, self.on_imported = is_busy, set_busy, on_imported
        self.batch = None
        self.content = None
        self.period_inputs = {}

    def build(self):
        with ui.card().classes('w-full p-4 gap-3'):
            ui.label('기존 상담기록관리 DB 가져오기').classes('text-lg font-bold')
            ui.label('XLSB의 인적사항등록·상담대장을 학생·집단 상담 또는 교사 자문으로 추가합니다. 대분류가 자문이면 인적사항의 성명을 교사로 등록합니다. 사례번호로 연결하며 기존 자료와 중복되면 중단합니다.')
            self.year = ui.number('인적사항 학년도', value=current_school_year(), min=1900, max=9999, step=1)
            with ui.dialog() as self.period_dialog, ui.card().classes('w-full max-w-lg max-h-[80vh] overflow-auto'):
                ui.label('교시별 시작 시간 (한국 시간)').classes('text-lg font-bold')
                ui.label('원본에 사용된 교시의 시작 시간을 입력하세요. 파일에서 발견한 교시도 자동으로 추가됩니다.')
                self.period_fields = ui.column().classes('w-full')
                ui.button('닫기', on_click=self.period_dialog.close)
            self.period_button = ui.button('교시별 시작 시간 설정', on_click=self.period_dialog.open)
            ui.label('시작 시각은 교시별 설정을 적용하며, 소요 시간은 원본의 시간(시) × 60 + 시간(분)으로 계산합니다. '
                     '원본 수식은 저장된 값을 읽으므로 Excel에서 계산·저장한 파일을 사용하세요.').classes('text-sm text-slate-500')
            self.upload = ui.upload(label='상담기록관리 XLSB 파일', auto_upload=True, max_files=1,
                max_file_size=MAX_BYTES, on_upload=self.receive,
                on_rejected=lambda: ui.notify('10MB 이하의 XLSB 파일 하나를 선택하세요.', type='warning')).props('accept=.xlsb')
            self.upload.on('removed', self.remove_file)
            self.recheck = ui.button('설정 적용 후 다시 검사', on_click=self.check)
            self.recheck.disable()
            self.preview = ui.column().classes('w-full gap-2')
            self.save_button = ui.button('검사한 자료를 DB에 추가', on_click=self.save)
            self.save_button.disable()
            self.year.on_value_change(self.clear)
            self.add_periods([str(n) for n in range(1, 8)])

    def add_periods(self, periods):
        with self.period_fields:
            for key in periods:
                if key and key not in self.period_inputs:
                    control = ui.input(f'{key} 교시 시작 시간', placeholder='HH:MM').props('type=time').classes('w-full')
                    control.on_value_change(self.clear)
                    self.period_inputs[key] = control

    def remove_file(self, *_):
        self.content = None
        self.clear()
        self.recheck.disable()

    def clear(self, *_):
        self.batch = None
        self.preview.clear()
        self.save_button.disable()

    def apply_busy(self, busy):
        for control in (self.year, self.period_button, self.upload, *self.period_inputs.values()):
            control.set_enabled(not busy)
        self.recheck.set_enabled(not busy and self.content is not None)
        self.save_button.set_enabled(not busy and self.batch is not None and not self.batch.errors)

    async def receive(self, event):
        if self.is_busy():
            return
        self.clear()
        self.content = None
        self.set_busy(True)
        try:
            if not event.file.name.lower().endswith('.xlsb'):
                raise ValueError('XLSB 파일을 선택하세요.')
            content = await event.file.read()
            rows = await run.io_bound(read_rows, content)
            self.add_periods(dict.fromkeys(period_key(row['교시']) for _, row in rows['상담대장']))
            self.content = content
        except (ValueError, TypeError, DatabaseError, OSError) as error:
            with self.preview:
                ui.label(str(error)).classes('text-red-700')
        finally:
            self.set_busy(False)
        if self.content is not None:
            await self.check()

    async def check(self):
        if self.is_busy() or self.content is None:
            return
        self.clear()
        self.set_busy(True)
        try:
            periods = {key: control.value for key, control in self.period_inputs.items()}
            self.batch = await run.io_bound(self.repository.preview, self.content, self.year.value, periods)
            self.render_results()
        except (ValueError, TypeError, DatabaseError, OSError) as error:
            self.batch = None
            with self.preview:
                ui.label(str(error)).classes('text-red-700')
        finally:
            self.set_busy(False)

    def render_results(self):
        batch = self.batch
        people = {person.key: person.value for person in batch.people}
        students = sum(isinstance(p.value, StudentInput) for p in batch.people)
        teachers = sum(isinstance(p.value, TeacherInput) for p in batch.people)
        consultations = sum(isinstance(log.value, ConsultationInput) for log in batch.logs)
        tests = sum(isinstance(log.value, PsychologicalTestInput) for log in batch.logs)

        def table(title, columns, rows):
            ui.label(f'{title} ({len(rows):,}건)').classes('text-base font-semibold mt-3')
            ui.table(columns=[dict(name=key, field=key, label=label, align='left', sortable=True)
                              for key, label in columns], rows=rows, row_key='id', pagination=10
                     ).props('flat bordered wrap-cells').classes('w-full')

        with self.preview:
            with ui.row().classes('w-full gap-3 flex-wrap'):
                for label, count in [('학생', students), ('교사', teachers),
                        ('집단', len(batch.people) - students - teachers),
                        ('상담', len(batch.logs) - consultations - tests), ('교사 자문', consultations),
                        ('심리검사', tests), ('오류', len(batch.errors))]:
                    with ui.card().classes('shadow-none border p-3 min-w-24'):
                        ui.label(label).classes('text-sm text-slate-500')
                        ui.label(f'{count:,}').classes('text-xl font-bold ' + ('text-red-700' if label == '오류' and count else 'text-teal-700'))
            if batch.errors:
                ui.label('오류를 수정한 뒤 다시 검사하세요. 오류가 있으면 전체 저장을 중단합니다.').classes('text-red-700')
                errors = []
                for index, error in enumerate(batch.errors):
                    match = re.match(r'^(인적사항등록|상담대장) (\d+)행: (.*)$', error, re.DOTALL)
                    errors.append(dict(id=index, sheet=match[1] if match else '파일/DB',
                                       row=int(match[2]) if match else None, message=match[3] if match else error))
                table('검사 오류', [('sheet', '시트'), ('row', '원본 행'), ('message', '확인할 내용')], errors)
            table('인적사항 등록 대상', [('row', '원본 행'), ('key', '사례번호'), ('kind', '등록 유형'),
                  ('name', '성명 / 집단명'), ('year', '학년도'), ('grade', '학년'), ('classroom', '반')],
                  [dict(id=p.row, row=p.row, key=p.key,
                        kind='학생' if isinstance(p.value, StudentInput) else '교사' if isinstance(p.value, TeacherInput) else '집단',
                        name=p.value.name, year=getattr(p.value, 'school_year', ''),
                        grade=getattr(p.value, 'grade', ''), classroom=getattr(p.value, 'classroom', '')) for p in batch.people])
            table('상담·자문·심리검사 등록 대상', [('row', '원본 행'), ('key', '사례번호'), ('kind', '등록 유형'),
                  ('name', '대상'), ('starts', '시작 시각 (한국)'), ('duration', '소요 시간 (분)'),
                  ('target', '상담/검사 대상'), ('area', '상담 분야'),
                  ('title', '제목'), ('author', '원본 상담자')],
                  [dict(id=log.row, row=log.row, key=log.key,
                        kind='심리검사' if isinstance(log.value, PsychologicalTestInput) else '교사 자문' if isinstance(log.value, ConsultationInput) else '개인 상담' if isinstance(log.value, CounselingInput) else '집단 상담',
                        name=people[log.key].name,
                        starts=f'{log.value.test_date} {log.value.test_time}' if isinstance(log.value, PsychologicalTestInput) else log.value.starts_at.strftime('%Y-%m-%d %H:%M'),
                        target=getattr(log.value, 'counseling_target', getattr(log.value, 'target', '')),
                        area=getattr(log.value, 'counseling_area', ''),
                        duration=log.value.duration_minutes, title=log.value.title, author=log.author) for log in batch.logs])
            ui.label('전체 검사 결과를 페이지별로 표시합니다. 열 제목을 누르면 정렬할 수 있습니다.').classes('text-sm text-slate-500')

    async def save(self):
        if self.is_busy() or self.batch is None or self.batch.errors:
            return
        self.set_busy(True)
        succeeded = False
        try:
            people, logs = await run.io_bound(self.repository.save, self.batch)
            self.clear()
            self.content = None
            self.upload.reset()
            ui.notify(f'인적사항 {people}건, 상담 {logs}건을 가져왔습니다.', type='positive')
            succeeded = True
        except (ValueError, DatabaseError) as error:
            self.batch = None
            with self.preview:
                ui.label(str(error)).classes('text-red-700')
        finally:
            self.set_busy(False)
        if succeeded:
            await self.on_imported('legacy')
