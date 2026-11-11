"""전체 명부의 동일인 확인, 누락 처리 및 편집 가능한 최종 검토."""
from collections import Counter
from copy import deepcopy

from nicegui import run, ui
from maeumnarae.views.shared.search_fields import search_input, search_select

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import ENROLLMENT_STATUSES, current_school_year
from maeumnarae.core.secure_upload import SecureUpload
from maeumnarae.repositories.students.year_preparation_repo import YearPreparationRepository
from maeumnarae.services.students.roster_import import COLUMNS, MAX_FILE_BYTES, TITLES, XLSX_MIME, import_template


class YearPreparationView:
    def __init__(self, database, kind, is_busy, set_busy, on_imported):
        self.repository = YearPreparationRepository(database)
        self.kind, self.is_busy, self.set_busy = kind, is_busy, set_busy
        self.on_imported = on_imported
        self.draft = None
        self.fix_errors_button = None
        self.review_editor = None
        self.review_card = None

    def build(self):
        ui.add_css('''
            @keyframes year-review-slide-up {
                from { transform: translateY(40px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
            .year-review-slide-up {
                animation: year-review-slide-up 240ms ease-out both;
            }
            @media (prefers-reduced-motion: reduce) {
                .year-review-slide-up { animation: none; }
            }
        ''')
        with ui.card().classes('w-full min-w-0 shadow-none border border-slate-200 p-4 gap-3'):
            ui.label('학생 진급' if self.kind == 'students' else '교사 명부 갱신').classes('text-lg font-bold')
            ui.label('새 학년도 전체 명단을 업로드하세요. 명단에 없는 기존 인원도 검토 대상입니다. 최종 확정 전에는 저장되지 않습니다.').classes('text-sm')
            current_year = current_school_year()
            with ui.row().classes('w-full items-center flex-nowrap overflow-x-auto'):
                self.year = search_select({current_year: f'{current_year}학년도'}, value=current_year,
                                      label='기준 학년도', with_input=True).props('outlined').classes('w-48 min-w-[200px]')
                ui.label('→').classes('text-xl text-slate-500 shrink-0')
                self.target = ui.label(f'대상 학년도: {current_year + 1}학년도').classes('whitespace-nowrap')
            self.year.on_value_change(lambda e: self.target.set_text(f'대상 학년도: {int(e.value) + 1}학년도' if e.value is not None else '기준 학년도를 선택하세요.'))
            self.download = ui.button('서식 다운로드', icon='download', on_click=self.download_template).props('outline')
            self.upload = SecureUpload(label=f'{TITLES[self.kind]} 전체 명단 XLSX', auto_upload=True, max_files=1,
                max_file_size=MAX_FILE_BYTES, on_upload=self.receive,
                on_rejected=lambda: ui.notify('10MB 이하의 XLSX 파일을 선택하세요.', type='warning')).props('accept=.xlsx').classes('w-full')
            self.upload.on('removed', lambda: self.clear(False))
            self.message = ui.label().classes('text-sm whitespace-pre-wrap')
        with ui.dialog().props('persistent') as self.dialog, ui.card().classes('w-full max-w-6xl max-h-[90vh] overflow-auto'):
            ui.label(f'{TITLES[self.kind]} 새 학년도 최종 확인').classes('text-xl font-bold')
            ui.label('검토 내용은 이 화면에서만 유지됩니다. 변경 전후를 확인하고 오류·미해결 항목을 모두 처리하세요.').classes('text-sm')
            self.summary = ui.label()
            with ui.row().classes('w-full shrink-0 items-center flex-nowrap overflow-x-auto'):
                self.search = search_input('이름 검색', on_change=lambda _: self.refresh()).classes('w-64')
                self.action = ui.select(['전체'], value='전체', label='처리 종류', on_change=lambda _: self.refresh()).classes('w-40')
                self.unresolved = ui.checkbox('오류·미해결만', on_change=lambda _: self.refresh())
                self.fix_errors_button = ui.button('오류 수정', icon='edit', on_click=self.edit_first_error).classes('ml-auto shrink-0')
                self.fix_errors_button.disable()
            self.table = ui.table(columns=[
                {'name': k, 'field': k, 'label': label, 'align': 'left'} for k, label in
                [('key', '파일 행 / 기존 ID'), ('name', '이름'), ('before', '변경 전'), ('after', '변경 후'),
                 ('action', '처리'), ('error', '확인 필요'), ('edit', '수정')]], rows=[], row_key='key', pagination=25).props('rows-per-page-label="페이지당 인원"').classes('w-full')
            self.table.add_slot('body-cell-edit', '''<q-td :props="props"><q-btn flat label="확인·수정" @click="$parent.$emit('edit', props.row.key)" /></q-td>''')
            self.table.on('edit', lambda e: self.edit(e.args))
            self.error = ui.label().classes('text-red-700 whitespace-pre-wrap')
            with ui.row().classes('w-full justify-end'):
                self.cancel = ui.button('취소', on_click=self.clear).props('flat')
                self.save_button = ui.button('최종 확정', icon='save', on_click=self.save)
            self.save_button.disable()
        ui.timer(0.01, self.load_school_years, once=True)

    async def load_school_years(self):
        try:
            years = await run.io_bound(self.repository.school_years)
        except (DatabaseError, ValueError):
            self.message.text = '학년도 목록을 불러오지 못했습니다.'
            return
        current_year = current_school_year()
        years = sorted({current_year, *(year for year in years if 1900 <= year <= 9998)}, reverse=True)
        self.year.set_options({year: f'{year}학년도' for year in years}, value=self.year.value)

    def apply_busy(self, value):
        for control in (self.year, self.download, self.upload, self.cancel):
            control.set_enabled(not value)
        errors = self.draft is not None and any(e['error'] for e in self.draft.validate())
        self.save_button.set_enabled(not value and self.draft is not None and not errors)
        if self.fix_errors_button is not None:
            self.fix_errors_button.set_enabled(not value and bool(errors))

    def clear(self, reset_upload=True):
        if self.is_busy():
            return
        self.draft = None
        self.table.rows = []
        self.dialog.close()
        self.save_button.disable()
        if self.fix_errors_button is not None:
            self.fix_errors_button.disable()
        if reset_upload:
            self.upload.reset()

    async def download_template(self):
        if self.is_busy():
            return
        self.set_busy(True)
        try:
            content = await run.io_bound(import_template, self.kind)
            ui.download.content(content, f'{TITLES[self.kind]}_일괄등록_서식.xlsx', media_type=XLSX_MIME)
        finally:
            self.set_busy(False)

    async def receive(self, event):
        if self.is_busy():
            return
        self.clear(False)
        self.message.text = '전체 명단을 검사하는 중입니다…'
        self.set_busy(True)
        try:
            if not event.file.name.lower().endswith('.xlsx'):
                raise ValueError('XLSX 파일을 업로드하세요.')
            if self.year.value is None or self.year.value != int(self.year.value):
                raise ValueError('기준 학년도를 정수로 입력하세요.')
            content = await event.file.read()
            self.draft = await run.io_bound(self.repository.preview, content, self.kind, int(self.year.value))
            actions = sorted({e['action'] for e in self.draft.entries()} | set(ENROLLMENT_STATUSES) | {'신규', '진급', '갱신', '전출', '미해결'})
            self.action.set_options(['전체', *actions], value='전체')
            self.search.value = ''
            self.unresolved.value = False
            self.error.text = ''
            self.refresh()
            self.message.text = ''
            self.dialog.open()
        except (DatabaseError, ValueError, OSError) as error:
            self.message.text = str(error)
        finally:
            self.set_busy(False)

    def describe(self, value, *, include_name=True):
        if not value:
            return '신규'
        name = f"{value.get('name', '')} / " if include_name else ''
        if self.kind == 'teachers':
            return f"{name}{value.get('contact', '')} / {value.get('extension', '')} / {value.get('responsibilities', '')}"
        grade = f"{value['grade']}학년" if value.get('grade') is not None else '학년 없음'
        classroom = f" {value['classroom']}반" if value.get('classroom') else ''
        return f"{name}{value.get('school_year', '')}년 {grade}{classroom} / {value.get('student_number') or '번호 없음'} / {value.get('status', '')} / 생년월일 {value.get('birth_date') or '미입력'}"

    def refresh(self):
        if self.draft is None:
            return
        entries = self.draft.validate()
        counts = Counter(e['action'] for e in entries)
        errors = sum(bool(e['error']) for e in entries)
        self.summary.text = f'{self.draft.base_year} → {self.draft.target_year}학년도 · 전체 {len(entries):,}명 · 오류·미해결 {errors:,}명 · ' + ' / '.join(f'{k} {v}명' for k, v in counts.items())
        query = (self.search.value or '').strip()
        self.table.rows = [dict(key=e['key'], name=e['value']['name'], before=self.describe(e['before'], include_name=False),
                               after=self.describe(e['value'], include_name=False), action=e['action'], error=e['error'])
                            for e in entries if (not query or query in e['value']['name'] or query in e['before'].get('name', ''))
                            and (self.action.value == '전체' or self.action.value == e['action'])
                            and (not self.unresolved.value or e['error'])]
        self.save_button.set_enabled(not errors and not self.is_busy())
        if self.fix_errors_button is not None:
            self.fix_errors_button.set_enabled(bool(errors) and not self.is_busy())

    def edit_first_error(self):
        if self.is_busy() or self.draft is None:
            return
        first = next((entry for entry in self.draft.validate() if entry['error']), None)
        if first is not None:
            self.edit(first['key'])

    def edit(self, key):
        if self.is_busy() or self.draft is None:
            return
        entry = next(e for e in self.draft.entries() if e['key'] == key)
        row = next((r for r in self.draft.rows if r.key == key), None)
        if self.kind == 'students' and row and not row.confirmed:
            linked = {r.person_id for r in self.draft.rows}
            base_candidate = next((pid for pid in row.candidates if pid not in linked
                                   and (pid, self.draft.base_year) in self.draft.enrollments), None)
            if base_candidate is not None:
                self.edit(f'old:{base_candidate}')
                return
        reverse = self.kind == 'students' and row is None and (entry['person_id'], self.draft.base_year) in self.draft.enrollments
        side_by_side = reverse or self.kind == 'teachers'
        teacher_before_fields = {}
        selected = replacement = target = None
        next_key = None
        if reverse:
            entry['before'].update(self.draft.enrollments[(entry['person_id'], self.draft.base_year)])
        width = 'max-w-6xl' if side_by_side else 'max-w-2xl'
        continuing = self.review_editor is not None and not self.review_editor.is_deleted
        if continuing:
            editor = self.review_editor
            self.review_card.clear()
            self.review_card.classes(remove='max-w-6xl max-w-2xl', add=width)
        else:
            with self.dialog:
                self.review_editor = editor = ui.dialog().props('persistent')
            with editor:
                self.review_card = ui.card().classes(f'w-full {width} p-6 max-h-[85vh] overflow-auto')

            def on_hide():
                if self.review_editor is editor:
                    self.review_editor = None
                    self.review_card = None
                editor.delete()

            editor.on('hide', on_hide)

        def advance():
            if next_key is not None:
                self.edit(next_key)
            else:
                editor.close()

        with self.review_card, ui.column().classes('w-full gap-4 shrink-0' + (' year-review-slide-up' if continuing else '')):
            ui.label('동일인 확인 및 정보 수정').classes('text-xl font-bold')
            if side_by_side:
                with ui.element('div').classes('w-full overflow-x-auto'):
                    with ui.element('div').classes('w-full min-w-[940px] grid grid-cols-[minmax(0,1fr)_30px_minmax(0,1fr)] items-start gap-4'):
                        connection_area = ui.column().classes('col-start-3 w-full gap-3')
                        with ui.column().classes('col-start-1 row-start-2 min-w-0 rounded-lg border bg-slate-50 p-4 gap-3').props('data-testid=promotion-before') as before_panel:
                            with ui.row().classes('w-full min-h-[56px] items-center'):
                                ui.label(f'기준 학년도 · {self.draft.base_year}학년도' if reverse else '기존 교사 명부').classes('text-lg font-bold')
                            ui.label('기존 학생 정보' if reverse else '기존 교사 정보 · 읽기 전용').classes('text-sm text-slate-500')
                        ui.label('→').classes('col-start-2 row-start-2 text-3xl text-slate-400 self-center').props('aria-label="변경 방향"')
                        with ui.column().classes('col-start-3 row-start-2 min-w-0 rounded-lg border p-4 gap-3').props('data-testid=promotion-after') as after_panel:
                            with ui.element('div').classes('w-full min-h-[56px] grid grid-cols-3 gap-4 items-center'):
                                ui.label(f'진급 학년도 · {self.draft.target_year}학년도' if reverse else f'갱신 학년도 · {self.draft.target_year}학년도').classes('col-span-2 text-lg font-bold')
                                status_slot = ui.column().classes('w-full min-w-0')
                            ui.label('연결할 학생을 선택하고 정보를 확인하세요.' if reverse else '업로드한 교사 정보를 확인하고 수정하세요.').classes('text-sm text-slate-500')
            with ui.column().classes('w-full gap-3') as before_info:
                if reverse:
                    before = entry['before']
                    for group in [
                        [('name', '이름'), ('nickname', '별명'), ('gender', '성별')],
                        [('school_year', '학년도'), ('grade', '학년'), ('classroom', '반'), ('student_number', '번호')],
                        [('birth_date', '생년월일'), ('student_contact', '학생 연락처')],
                    ]:
                        with ui.row().classes('w-full flex-nowrap items-start'):
                            for field, label in group:
                                ui.input(label, value=str(before.get(field) or '')).props('outlined readonly').classes('flex-1 min-w-0')
                    ui.textarea('학생 메모', value=before.get('notes') or '').props('outlined readonly rows=1 input-style="resize: none"').classes('w-full')
                    ui.input('보호자 연락처', value=before.get('guardian_contact') or '').props('outlined readonly').classes('w-full')
                elif self.kind == 'teachers':
                    before = self.draft.previous(row.replacement_id) if row and row.replacement_id else entry['before']
                    for group in [COLUMNS['teachers'][:2], COLUMNS['teachers'][2:]]:
                        with ui.row().classes('w-full flex-nowrap items-start'):
                            for field, label, _ in group:
                                teacher_before_fields[field] = ui.input(label, value=str(before.get(field) or '')).props('outlined readonly').classes('flex-1 min-w-0')
                else:
                    ui.label('변경 전: ' + self.describe(entry['before'])).classes('text-sm whitespace-pre-wrap')
                    if entry['before']:
                        with ui.expansion('변경 전 상세 정보', value=reverse).classes('w-full'):
                            for field, label, _ in COLUMNS[self.kind]:
                                ui.label(f"{label}: {entry['before'].get(field) or '미입력'}").classes('whitespace-pre-wrap break-all')
            if side_by_side:
                before_info.move(before_panel)
            error_label = ui.label().classes('text-red-700 whitespace-pre-wrap')
            with ui.column().classes('w-full gap-3') as after_info:
                with ui.column().classes('w-full gap-3') as connection_controls:
                    if reverse:
                        candidates = sorted((r for r in self.draft.rows if r.person_id is None),
                                            key=lambda r: (entry['person_id'] not in r.candidates,
                                                           r.source['name'] != entry['before']['name']))
                        options = {'': '명부 연결 없음 (누락 상태 지정)'}
                        options.update({r.key: f'{r.key} · ' + self.describe(r.source) for r in candidates})
                        with ui.row().classes('w-full flex-nowrap items-center') as connection_row:
                            target = search_select(options, value='', label='진급 학년도 명부 검색·연결', with_input=True).props('filled').classes('flex-1 min-w-0')
                        ui.label('왼쪽 기준 학년도 학생과 동일한 학생을 진급 명부에서 선택한 뒤 편집 반영을 누르세요.').classes('text-sm')
                    elif row:
                        candidates = list(row.candidates) + [pid for pid in self.draft.people if pid not in row.candidates]
                        options = {0: '신규 학생' if self.kind == 'students' else '새 교사 (연결 없음)'}
                        options.update({pid: f'ID {pid} · ' + self.describe(self.draft.previous(pid)) for pid in candidates})
                        selected = search_select(options, value=row.person_id or 0, label='기존 인원 검색·연결', with_input=True).classes('w-full')
                        replacement = None
                        if self.kind == 'teachers':
                            replacement = search_select(options, value=row.replacement_id or 0, label='다른 사람인 경우: 교체할 기존 교사', with_input=True).classes('w-full')

                    if row is None and self.kind == 'students':
                        def retain():
                            nonlocal next_key
                            self.draft.retain(entry['person_id'])
                            self.refresh()
                            entries = self.draft.validate()
                            index = next((i for i, item in enumerate(entries) if item['key'] == key), -1)
                            next_key = next((item['key'] for item in entries[index + 1:] + entries[:index + 1]
                                             if item['error']), None)
                            linked = any(r.person_id == entry['person_id'] for r in self.draft.rows)
                            ui.notify('재학 상태를 유지하고 동일 학년 학생을 연결했습니다.' if linked else
                                      '재학 상태를 유지합니다. 동명이인을 확인하여 명부를 연결하거나 학년·반을 입력하세요.')
                            advance()
                        retain_button = ui.button('유예 처리', on_click=retain).props('outline').classes('shrink-0')
                        if reverse:
                            retain_button.move(connection_row)
                if side_by_side:
                    connection_controls.move(connection_area)
                fields = {}
                if self.kind == 'students':
                    value = entry['value']
                    with ui.column().classes('w-full gap-3'):
                        with ui.row().classes('w-full flex-nowrap items-start'):
                            fields['name'] = ui.input('이름', value=value.get('name') or '').props('outlined').classes('flex-1 min-w-0')
                            fields['nickname'] = ui.input('별명', value=value.get('nickname') or '').props('outlined').classes('flex-1 min-w-0')
                            fields['gender'] = ui.select(['남', '여', '기타'], label='성별',
                                                        value=value.get('gender')).props('outlined clearable').classes('flex-1 min-w-0')
                        with ui.row().classes('w-full flex-nowrap items-start'):
                            ui.number('학년도', value=self.draft.target_year, precision=0).props('outlined readonly').classes('flex-1 min-w-0')
                            grade_options = list(range(1, self.draft.max_grade + 1))
                            fields['grade'] = ui.select(grade_options, label='학년',
                                                       value=value.get('grade') if value.get('grade') in grade_options else None).props('outlined').classes('flex-1 min-w-0')
                            fields['classroom'] = ui.input('반', value=value.get('classroom') or '').props('outlined').classes('flex-1 min-w-0')
                            fields['student_number'] = ui.input('번호', value=value.get('student_number') or '').props('outlined').classes('flex-1 min-w-0')
                        with ui.row().classes('w-full flex-nowrap items-start'):
                            fields['birth_date'] = ui.date_input('생년월일', value=str(value.get('birth_date') or '')).props('outlined').classes('flex-1 min-w-0')
                            fields['student_contact'] = ui.input('학생 연락처', value=value.get('student_contact') or '').props('outlined mask="###-####-####" inputmode="numeric"').classes('flex-1 min-w-0')
                        fields['notes'] = ui.textarea('학생 메모', value=value.get('notes') or '').props('outlined').classes('w-full')
                        if reverse:
                            fields['notes'].props('rows=1 input-style="resize: none"')
                        fields['guardian_contact'] = ui.input('보호자 연락처', value=value.get('guardian_contact') or '').props('outlined mask="###-####-####" inputmode="numeric"').classes('w-full')
                    fields['status'] = ui.select(ENROLLMENT_STATUSES, value=value.get('status') or None, label='학적 상태').props('outlined')
                    def update_grade_state():
                        grade_not_applicable = fields['status'].value in ('졸업', '조기졸업', '자퇴', '전학')
                        if grade_not_applicable:
                            fields['grade'].value = None
                        fields['grade'].set_enabled(not grade_not_applicable)
                    fields['status'].on_value_change(lambda _: update_grade_state())
                    update_grade_state()
                else:
                    for group in [COLUMNS['teachers'][:2], COLUMNS['teachers'][2:]]:
                        with ui.row().classes('w-full flex-nowrap items-start'):
                            for field, label, _ in group:
                                fields[field] = ui.input(label, value=str(entry['value'].get(field) or '')).props('outlined').classes('flex-1 min-w-0')

            if side_by_side:
                after_info.move(after_panel)

            def staged_link():
                draft = deepcopy(self.draft)
                edit_key = key
                if target is not None and target.value:
                    edit_key = target.value
                    draft.link(edit_key, entry['person_id'])
                elif row:
                    person_id = selected.value or None
                    replacement_id = replacement.value or None if replacement is not None else None
                    if not row.confirmed or (person_id, replacement_id) != (row.person_id, row.replacement_id):
                        draft.link(key, person_id, replacement_id)
                return draft, edit_key

            def preview_link():
                try:
                    draft, edit_key = staged_link()
                    preview = next(e['value'] for e in draft.entries() if e['key'] == edit_key)
                    for field, control in fields.items():
                        value = preview.get(field)
                        if field == 'birth_date':
                            value = str(value or '')
                        elif field not in ('grade', 'gender', 'status'):
                            value = value or ''
                        control.value = value
                    if self.kind == 'students':
                        update_grade_state()
                    elif teacher_before_fields:
                        person_id = (selected.value or replacement.value) if selected is not None else entry['person_id']
                        before = draft.previous(person_id) if person_id else {}
                        for field, control in teacher_before_fields.items():
                            control.value = str(before.get(field) or '')
                    error_label.text = ''
                except ValueError as error:
                    error_label.text = str(error)

            for control in (target, selected, replacement):
                if control is not None:
                    control.on_value_change(preview_link)

            def apply():
                nonlocal next_key
                try:
                    draft, edit_key = staged_link()
                except ValueError as error:
                    error_label.text = str(error)
                    return
                changes = {k: control.value for k, control in fields.items()}
                if self.kind == 'students':
                    changes['student_number'] = changes['student_number'] or None
                    changes['birth_date'] = changes['birth_date'] or None
                    if changes.get('status') != '재학':
                        changes.update(classroom='', student_number=None)
                edited_row = next((r for r in draft.rows if r.key == edit_key), None)
                if edited_row:
                    edited_row.edits.update(changes)
                else:
                    draft.missing_edits.setdefault(entry['person_id'], {}).update(changes)
                entries = draft.validate()
                current = next((e for e in entries if e['key'] == edit_key), None)
                if current and current['error']:
                    error_label.text = current['error']
                    return
                self.draft = draft
                self.refresh()
                index = next((i for i, e in enumerate(entries) if e['key'] == edit_key), -1)
                next_key = next((e['key'] for e in entries[index + 1:] + entries[:index + 1] if e['error']), None)
                advance()
            with ui.row().classes('w-full flex-nowrap items-center justify-end') as actions:
                if self.kind == 'students':
                    if reverse:
                        fields['status'].classes('w-full min-w-0').move(status_slot)
                    else:
                        fields['status'].classes('w-32 mr-auto').move(actions)
                ui.button('닫기', on_click=editor.close).props('flat')
                ui.button('편집 반영', on_click=apply)
        if not continuing:
            editor.open()

    async def save(self):
        if self.is_busy() or self.draft is None:
            return
        self.set_busy(True)
        succeeded = False
        try:
            count = await run.io_bound(self.repository.save, self.draft)
            self.draft = None
            self.dialog.close()
            self.table.rows = []
            self.upload.reset()
            self.message.text = f'{TITLES[self.kind]} {count:,}명의 새 학년도 준비를 완료했습니다.'
            succeeded = True
        except (DatabaseError, ValueError) as error:
            self.error.text = str(error)
        finally:
            self.set_busy(False)
        if succeeded:
            await self.on_imported(self.kind)
