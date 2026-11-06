"""XLSB 이관 옵션, 미리보기 및 명시적 저장."""

from maeumnarae.views.shared.settings_card import settings_card
from maeumnarae.views.shared.time_inputs import storage_time, time_input

from maeumnarae.core.secure_upload import SecureUpload

from nicegui import run, ui
import re

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import StudentInput, TeacherInput, ConsultationInput, CounselingInput, PsychologicalTestInput, EducationEventInput, current_school_year
from maeumnarae.repositories.data_management.legacy_import_repo import ALREADY_IMPORTED, LegacyImportRepository
from maeumnarae.services.data_management.legacy_import import MAX_BYTES, read_rows, period_key, DESTINATIONS, SPECIAL_LAWS, text, excel_day


def correction_text(label, value):
    """날짜는 읽을 수 있게 표시하고 잘못된 원본 값은 수정할 수 있도록 남긴다."""
    if label in ('일자', '상담일자', '생년월일') and text(value):
        try:
            return excel_day(value).isoformat()
        except (ValueError, TypeError, OverflowError):
            pass
    return text(value)


class LegacyImportView:
    def __init__(self, database, is_busy, set_busy, on_imported):
        self.repository = LegacyImportRepository(database)
        self.is_busy, self.set_busy, self.on_imported = is_busy, set_busy, on_imported
        self.batch = None
        self.content = None
        self.period_inputs = {}
        self.rows = {}
        self.corrections, self.destinations, self.excluded = {}, {}, set()
        self.special_laws = {}
        self.saved_periods = self.repository.load_period_times() if database is not None else {}

    def build(self, *, collapsible: bool = False):
        with settings_card('울산형 상담기록관리 DB 가져오기', 'drive_folder_upload',
                           'XLSB의 인적사항등록·상담대장을 상담·교사 자문·심리검사·교육/행사로 추가합니다. 대분류가 자문이면 인적사항의 성명을 교사로 등록합니다. 사례번호로 연결하며 기존 대상과 식별 정보가 일치하면 연결합니다.', collapsible=collapsible):
            self.year = ui.number('자료의 학년도', value=current_school_year(), min=1900, max=9999, step=1)
            with ui.dialog() as self.period_dialog, ui.card().classes('w-full max-w-lg max-h-[80vh] overflow-auto'):
                ui.label('교시별 시작 시간 (한국 시간)').classes('text-lg font-bold')
                ui.label('원본에 사용된 교시의 시작 시간을 입력하세요. 파일에서 발견한 교시도 자동으로 추가됩니다.')
                self.period_fields = ui.column().classes('w-full')
                ui.button('닫기', on_click=self.period_dialog.close)
            self.period_button = ui.button('교시별 시작 시간 설정', on_click=self.period_dialog.open)
            ui.label('시작 시각은 교시별 설정을 적용하며, 소요 시간은 원본의 시간(시) × 60 + 시간(분)으로 계산합니다. '
                     '원본 수식은 저장된 값을 읽으므로 Excel에서 계산·저장한 파일을 사용하세요.').classes('text-sm text-slate-500')
            self.upload = SecureUpload(label='상담기록관리 XLSB 파일', auto_upload=True, max_files=1,
                max_file_size=MAX_BYTES, on_upload=self.receive,
                on_rejected=lambda: ui.notify('10MB 이하의 XLSB 파일 하나를 선택하세요.', type='warning')).props('accept=.xlsb')
            self.upload.on('removed', self.remove_file)
            self.cancel_upload = ui.button('업로드 취소', on_click=self.cancel_file)
            self.cancel_upload.disable()
            self.recheck = ui.button('설정 적용 후 다시 검사', on_click=self.check)
            self.recheck.disable()
            self.preview = ui.column().classes('w-full gap-2')
            self.save_button = ui.button('검사한 자료를 DB에 추가', on_click=self.save)
            self.save_button.disable()
            self.year.on_value_change(self.clear)
            self.add_periods(list(dict.fromkeys(
                ['일과전'] + [str(n) for n in range(1, 8)] + ['점심시간', '쉬는시간', '방과후'] + list(self.saved_periods)
            )))

    def add_periods(self, periods):
        with self.period_fields:
            for key in periods:
                if key and key not in self.period_inputs:
                    label = f'{key} 교시' if key.isdigit() else key
                    control = time_input(f'{label} 시작 시간', value=self.saved_periods.get(key, '')).classes('w-full')
                    control.on_value_change(self.period_changed)
                    self.period_inputs[key] = control

    def period_changed(self, *_):
        self.clear()
        if self.repository.database is None:
            return
        try:
            periods = {key: storage_time(control.value) for key, control in self.period_inputs.items()}
            self.repository.save_period_times(periods)
            self.saved_periods = periods
        except (ValueError, DatabaseError, OSError) as error:
            ui.notify(f'교시 시간 저장 실패: {error}', type='warning')

    def cancel_file(self):
        if self.is_busy():
            return
        self.upload.reset()
        self.remove_file()

    def remove_file(self, *_):
        if self.is_busy():
            return
        self.content = None
        self.rows = {}
        self.corrections, self.destinations, self.excluded = {}, {}, set()
        self.special_laws = {}
        self.cancel_upload.disable()
        self.clear()
        self.recheck.disable()

    def clear(self, *_):
        self.batch = None
        self.preview.clear()
        self.save_button.disable()

    def apply_busy(self, busy):
        for control in (self.year, self.period_button, self.upload, *self.period_inputs.values()):
            control.set_enabled(not busy)
        self.cancel_upload.set_enabled(not busy)
        self.recheck.set_enabled(not busy and self.content is not None)
        self.save_button.set_enabled(not busy and self.batch is not None and not self.batch.errors)

    async def receive(self, event):
        if self.is_busy():
            return
        self.remove_file()
        self.set_busy(True)
        try:
            if not event.file.name.lower().endswith('.xlsb'):
                raise ValueError('XLSB 파일을 선택하세요.')
            content = await event.file.read()
            rows = await run.io_bound(read_rows, content)
            self.add_periods(dict.fromkeys(period_key(row['교시']) for _, row in rows['상담대장']))
            self.rows = rows
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
            periods = {key: storage_time(control.value) for key, control in self.period_inputs.items()}
            self.batch = await run.io_bound(self.repository.preview, self.content, self.year.value, periods,
                corrections=self.corrections, destinations=self.destinations, excluded=self.excluded, special_laws=self.special_laws)
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
        specials = sum(bool(log.special_law) for log in batch.logs)
        events = sum(isinstance(log.value, EducationEventInput) for log in batch.logs)

        def table(title, columns, rows):
            ui.label(f'{title} ({len(rows):,}건)').classes('text-base font-semibold mt-3')
            ui.table(columns=[dict(name=key, field=key, label=label, align='left', sortable=True)
                              for key, label in columns], rows=rows, row_key='id', pagination=10
                     ).props('flat bordered wrap-cells').classes('w-full')

        with self.preview:
            with ui.row().classes('w-full gap-3 flex-wrap'):
                for label, count in [('학생', students), ('교사', teachers),
                        ('집단', len(batch.people) - students - teachers),
                        ('상담', len(batch.logs) - consultations - tests - events - specials), ('교사 자문', consultations),
                        ('심리검사', tests), ('특별교육', specials), ('교육/행사', events), ('오류', len(batch.errors))]:
                    with ui.card().classes('shadow-none border p-3 min-w-24'):
                        ui.label(label).classes('text-sm text-slate-500')
                        ui.label(f'{count:,}').classes('text-xl font-bold ' + ('text-red-700' if label == '오류' and count else 'text-primary'))
            if batch.errors:
                message = ('업로드 한 파일을 다시 확인하세요. 이미 등록한 파일입니다.'
                           if ALREADY_IMPORTED in batch.errors else
                           '오류를 수정한 뒤 다시 검사하세요. 오류가 있으면 전체 저장을 중단합니다.')
                ui.label(message).classes('text-red-700')
                errors = []
                for index, error in enumerate(batch.errors):
                    match = re.match(r'^(인적사항등록|상담대장) (\d+)행: (.*)$', error, re.DOTALL)
                    errors.append(dict(id=index, sheet=match[1] if match else '파일/DB',
                                       row=int(match[2]) if match else None, message=match[3] if match else error))
                table('검사 오류', [('sheet', '시트'), ('row', '원본 행'), ('message', '확인할 내용')], errors)
            if self.rows:
                ui.button('행 수정 / 일지 지정 / 제외', on_click=self.open_corrections).set_enabled(bool(self.row_errors()))
                if self.excluded:
                    ui.label(f'사용자가 제외한 행: {len(self.excluded)}건')
                    ui.button('제외한 행 모두 복원 후 다시 검사', on_click=self.restore_excluded)
            if ALREADY_IMPORTED in batch.errors:
                return
            table('인적사항 등록 대상', [('row', '원본 행'), ('key', '사례번호'), ('kind', '등록 유형'),
                  ('name', '성명 / 집단명'), ('year', '학년도'), ('grade', '학년'), ('classroom', '반')],
                  [dict(id=p.row, row=p.row, key=p.key,
                        kind='학생' if isinstance(p.value, StudentInput) else '교사' if isinstance(p.value, TeacherInput) else '집단',
                        name=p.value.name, year=getattr(p.value, 'school_year', ''),
                        grade=getattr(p.value, 'grade', ''), classroom=getattr(p.value, 'classroom', '')) for p in batch.people])
            table('일지 등록 대상', [('row', '원본 행'), ('key', '사례번호'), ('kind', '등록 유형'),
                  ('name', '대상'), ('starts', '시작 시각 (한국)'), ('duration', '소요 시간 (분)'),
                  ('target', '상담/검사 대상'), ('area', '상담 분야'),
                  ('title', '제목'), ('author', '원본 상담자')],
                  [dict(id=log.row, row=log.row, key=log.key,
                        kind='특별교육' if log.special_law else '교육/행사' if isinstance(log.value, EducationEventInput) else '심리검사' if isinstance(log.value, PsychologicalTestInput) else '교사 자문' if isinstance(log.value, ConsultationInput) else '개인 상담' if isinstance(log.value, CounselingInput) else '집단 상담',
                        name=people[log.key].name if log.key in people else '',
                        starts=f'{log.value.event_date} {log.value.event_time}' if isinstance(log.value, EducationEventInput) else f'{log.value.test_date} {log.value.test_time}' if isinstance(log.value, PsychologicalTestInput) else log.value.starts_at.strftime('%Y-%m-%d %H:%M'),
                        target=getattr(log.value, 'counseling_target', getattr(log.value, 'target', '')),
                        area=getattr(log.value, 'consultation_area', getattr(log.value, 'counseling_area', '')),
                        duration=log.value.duration_minutes, title=log.value.title, author=log.author) for log in batch.logs])
            ui.label('전체 검사 결과를 페이지별로 표시합니다. 열 제목을 누르면 정렬할 수 있습니다.').classes('text-sm text-slate-500')

    def row_errors(self):
        errors = {}
        for error in self.batch.errors if self.batch is not None else ():
            match = re.match(r'^(인적사항등록|상담대장) (\d+)행: (.*)$', error, re.DOTALL)
            if match:
                errors.setdefault((match[1], int(match[2])), []).append(match[3])
        return errors

    async def restore_excluded(self):
        if self.is_busy():
            return
        self.excluded.clear()
        await self.check()

    def open_corrections(self):
        if self.is_busy():
            return
        records = {(sheet, number): row for sheet, rows in self.rows.items() for number, row in rows}
        errors = self.row_errors()
        if not any(key in errors for key in records):
            return
        with self.preview.parent_slot, ui.dialog() as dialog, ui.card().classes('w-full max-w-3xl max-h-[85vh] overflow-auto'):
            ui.label('행 수정 및 일지 지정').classes('text-lg font-bold')
            ui.label('오류가 있는 행만 표시합니다. 수정사항 저장 후 다시 검사하고 다음 오류를 이어서 수정합니다. DB 등록은 마지막에 별도로 진행합니다.')
            progress = ui.label()
            choices = {f'{sheet}:{number}': f'{sheet} {number}행 · {text(row.get("성명/집단명"))}'
                       for (sheet, number), row in records.items() if (sheet, number) in errors}
            selector = ui.select(choices, label='수정할 행', value=next(iter(choices))).classes('w-full').props('use-input')
            fields = ui.column().classes('w-full')
            controls = {}
            state = {"saving": False}

            def show():
                fields.clear()
                controls.clear()
                state['excluded'] = state['route'] = state['law'] = None
                if not selector.value:
                    return
                sheet, number = selector.value.rsplit(':', 1)
                key = (sheet, int(number))
                state['key'] = key
                controls.clear()
                row = records[key] | self.corrections.get(key, {})
                with fields:
                    for message in errors.get(key, []):
                        ui.label(message).classes('text-red-700')
                    state['excluded'] = ui.checkbox('이 행 제외', value=key in self.excluded)
                    state['route'] = (ui.select(['자동'] + DESTINATIONS, label='등록할 일지',
                        value=self.destinations.get(key[1], '자동')).classes('w-full') if sheet == '상담대장' else None)
                    if state['route'] is not None:
                        state['law'] = ui.select(SPECIAL_LAWS, label='특별교육 근거 법률',
                            value=self.special_laws.get(key[1])).classes('w-full')
                        state['law'].bind_visibility_from(state['route'], 'value', lambda value: value == '특별교육')
                    with ui.grid(columns=2).classes('w-full'):
                        for label, value in row.items():
                            display = correction_text(label, value)
                            control = (ui.textarea(label, value=display) if label in ('상담내용', '비고')
                                       else ui.input(label, value=display))
                            if label in ('일자', '상담일자', '생년월일'):
                                control.props('placeholder=YYYY-MM-DD')
                            controls[label] = control

            async def apply():
                nonlocal errors
                if self.is_busy() or state['saving'] or not selector.value:
                    return
                key = state['key']
                original = records[key]
                # 변경하지 않은 Excel 날짜/숫자는 원래 타입을 유지한다.
                self.corrections[key] = {label: control.value for label, control in controls.items()
                                         if control.value != correction_text(label, original[label])}
                if state['excluded'].value:
                    self.excluded.add(key)
                else:
                    self.excluded.discard(key)
                if state['route'] is not None:
                    route = state['route'].value
                    if route == '자동':
                        self.destinations.pop(key[1], None)
                    else:
                        self.destinations[key[1]] = route
                    if route == '특별교육' and state['law'].value:
                        self.special_laws[key[1]] = state['law'].value
                    else:
                        self.special_laws.pop(key[1], None)
                self.add_periods([period_key(self.corrections[key].get('교시', original.get('교시', '')))])
                state['saving'] = True
                for control in (selector, save, close, *controls.values(), state['excluded'], state['route'], state['law']):
                    if control is not None:
                        control.disable()
                try:
                    await self.check()
                    if self.batch is None:
                        progress.set_text('재검사하지 못했습니다. 설정이나 DB 상태를 확인한 뒤 다시 저장하세요.')
                        return
                    errors = self.row_errors()
                    choices = {f'{sheet}:{number}': f'{sheet} {number}행 · {text(row.get("성명/집단명"))}'
                               for (sheet, number), row in records.items() if (sheet, number) in errors}
                    current = f'{key[0]}:{key[1]}'
                    selector.set_options(choices, value=current if current in choices else next(iter(choices), None))
                    show()
                    if choices:
                        progress.set_text(f'수정사항 저장 완료 · 남은 오류 행 {len(choices)}건')
                    elif self.batch.errors:
                        progress.set_text('행 오류 처리가 완료되었습니다. 검사 결과의 파일/DB 오류를 확인하세요.')
                    else:
                        progress.set_text('모든 오류가 해결되었습니다. 창을 닫고 검사한 자료를 DB에 추가하세요.')
                finally:
                    state['saving'] = False
                    for control in (selector, close, *controls.values(), state['excluded'], state['route'], state['law']):
                        if control is not None:
                            control.enable()
                    save.set_enabled(bool(selector.value))

            selector.on_value_change(show)
            show()
            with ui.row():
                save = ui.button('수정사항 저장 후 다음 오류', on_click=apply)
                close = ui.button('닫기', on_click=dialog.close)
        dialog.open()

    async def save(self):
        if self.is_busy() or self.batch is None or self.batch.errors:
            return
        self.set_busy(True)
        succeeded = False
        try:
            people, logs = await run.io_bound(self.repository.save, self.batch)
            self.clear()
            self.content = None
            self.rows = {}
            self.corrections, self.destinations, self.excluded = {}, {}, set()
            self.special_laws = {}
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
