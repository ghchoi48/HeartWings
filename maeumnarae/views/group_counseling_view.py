"""집단 목록, 선택 집단의 상세 정보와 회기별 상담일지."""

from datetime import date, datetime
from copy import deepcopy
from collections.abc import Awaitable, Callable

from maeumnarae.views.journal_pagination import PAGE_SIZE, load_page

from nicegui import run, ui
from maeumnarae.views.journal_defaults import default_duration_minutes
from maeumnarae.views.journal_print_view import list_print_tools

from maeumnarae.views.attachment_view import attachment_button

from maeumnarae.views.delete_action import delete_button

from maeumnarae.views.time_inputs import parse_time, time_input

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import GroupCounseling, GroupCounselingInput, GroupLogInput
from maeumnarae.repositories.group_counseling_repo import GroupCounselingRepository
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.views.counseling_content import clean_html
from maeumnarae.views.counseling_view import KST, STATUSES



class GroupCounselingView:
    def __init__(self, repository: GroupCounselingRepository,
                 on_saved: Callable[[], Awaitable[None]] | None = None):
        self.repository = repository
        self.students = StudentRepository(repository.database)
        self.on_saved = on_saved
        self.selected: GroupCounseling | None = None
        self.list_request = 0
        self.selection_request = 0
        self.log_request = 0
        self.log_offset = 0
        self.editor_open = False

    def build(self) -> None:
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            ui.label('집단 상담').classes('text-3xl font-bold text-slate-800')
            ui.label('집단을 선택하고 상세 정보와 상담 일지를 관리하세요.').classes('text-slate-500')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[3fr_7fr] items-start gap-6'):
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('집단 상담 목록').classes('text-xl font-bold')
                        ui.button('집단 추가', icon='group_add', on_click=lambda: self.open_editor())
                    self.table = ui.table(columns=[
                        dict(name=key, label=label, field=key, align='left')
                        for key, label in [('school_year', '학년도'), ('name', '집단명'), ('facilitator', '진행자')]
                    ], rows=[], row_key='id', pagination=10).classes('w-full').props(
                        'flat no-data-label="등록된 집단 상담이 없습니다" no-results-label="검색 결과가 없습니다"')
                    with self.table.add_slot('top'):
                        ui.input('집단 검색').props('outlined dense clearable debounce=300').classes('w-full').bind_value(self.table, 'filter')
                    self.table.on('rowClick', self.row_clicked, js_handler='(event, row) => emit(row.id)')
                    self.list_message = ui.label().classes('text-sm text-red-700')
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5 gap-4'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('집단 상담 상세 정보').classes('text-xl font-bold')
                        with ui.row().classes('items-center gap-2'):
                            delete_button(self.repository.database, 'group', lambda: self.selected, self.after_group_deleted, blocked=lambda: self.editor_open).bind_visibility_from(self, 'selected', backward=lambda value: value is not None)
                            self.edit = ui.button('정보 수정', icon='edit', on_click=lambda: self.open_editor(edit_group=True))
                            self.edit.disable()
                    self.details = ui.column().classes('w-full gap-3')
                    self.detail_message = ui.label('왼쪽 목록에서 집단을 선택해 주세요.').classes('text-slate-500')
                    ui.separator().classes('my-2')
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('집단 상담 일지 목록').classes('text-xl font-bold')
                        self.add_log = ui.button('새 집단 상담 일지', icon='edit_note', on_click=lambda: self.open_editor(log=True))
                        self.add_log.disable()
                    self.logs = ui.column().classes('w-full gap-3')
                    self.log_message = ui.label().classes('text-sm text-slate-500')
                    with ui.row().classes('w-full justify-end items-center'):
                        self.previous = ui.button('이전', on_click=lambda: self.log_page(-1)).props('flat')
                        self.page_label = ui.label()
                        self.next = ui.button('다음', on_click=lambda: self.log_page(1)).props('flat')
                        self.previous.disable()
                        self.next.disable()
        ui.timer(0.01, self.load_groups, once=True)

    async def row_clicked(self, event) -> None:
        await self.select_group(event.args)

    async def load_groups(self) -> None:
        self.list_request += 1
        request = self.list_request
        self.list_message.text = ''
        self.table.props('loading')
        try:
            groups = []
            while True:
                batch = await run.io_bound(self.repository.list, limit=1000, offset=len(groups))
                if request != self.list_request:
                    return
                groups.extend(batch)
                if len(batch) < 1000:
                    break
            self.table.rows = [dict(id=g.id, school_year=g.school_year if g.school_year is not None else '미입력',
                                    name=g.name, facilitator=g.facilitator or '미입력') for g in groups]
            self.table.update()
        except DatabaseError as error:
            if request == self.list_request:
                self.list_message.text = str(error)
        finally:
            if request == self.list_request:
                self.table.props(remove='loading')

    async def select_group(self, group_id: int) -> None:
        self.selection_request += 1
        request = self.selection_request
        self.log_request += 1
        self.selected = None
        if hasattr(self, 'pdf_tools'):
            self.pdf_tools.set_scope(None)
        self.details.clear()
        self.logs.clear()
        self.edit.disable()
        self.add_log.disable()
        self.previous.disable()
        self.next.disable()
        self.log_message.text = self.page_label.text = ''
        self.detail_message.text = '집단 상담 정보를 불러오는 중입니다…'
        try:
            group = await run.io_bound(self.repository.get, group_id)
        except DatabaseError as error:
            if request == self.selection_request:
                self.detail_message.text = str(error)
            return
        if request != self.selection_request:
            return
        if group is None:
            self.detail_message.text = '집단 상담을 찾을 수 없습니다. 다른 집단을 선택해 주세요.'
            return
        self.selected = group
        self.detail_message.text = ''
        with self.details:
            ui.label(group.name).classes('text-xl font-semibold')
            with ui.row().classes('w-full flex-nowrap items-start gap-4'):
                for label, value in [('진행자', group.facilitator), ('운영 기간', group.period),
                                     ('상담 영역', group.counseling_area)]:
                    with ui.column().classes('flex-1 min-w-0 gap-1'):
                        ui.label(label).classes('font-semibold text-slate-600')
                        ui.label(value or '미입력').classes('whitespace-pre-wrap break-words w-full')
            for label, value in [('상담 목표', group.purpose), ('참여 학생', group.participant_labels),
                                 ('비고', group.notes)]:
                with ui.column().classes('gap-1 w-full'):
                    ui.label(f'참여 학생 ({len(group.student_ids)}명)' if label == '참여 학생' else label).classes('font-semibold text-slate-600')
                    if label == '참여 학생':
                        if value:
                            with ui.row().classes('w-full flex-wrap gap-2'):
                                for participant in value:
                                    ui.chip(participant, icon='person', color='teal-1', text_color='teal-9')
                        else:
                            ui.label('연결된 참여 학생이 없습니다.').classes('text-slate-500')
                    else:
                        ui.label(value or '미입력').classes('whitespace-pre-wrap break-words w-full')
        self.edit.enable()
        self.add_log.enable()
        self.log_offset = 0
        await self.load_logs()

    async def after_group_deleted(self):
        await self.select_group(None)
        await self.load_groups()
        if self.on_saved:
            await self.on_saved()

    async def after_log_deleted(self):
        self.log_offset = 0
        await self.load_logs()
        if self.on_saved:
            await self.on_saved()

    async def log_page(self, direction: int) -> None:
        self.log_offset = max(0, self.log_offset + direction * PAGE_SIZE)
        await self.load_logs()

    async def load_logs(self) -> None:
        if self.selected is None:
            return
        self.log_request += 1
        request = self.log_request
        self.logs.clear()
        self.previous.disable()
        self.next.disable()
        self.log_message.text = '상담 일지를 불러오는 중입니다…'
        try:
            entries, offset, pages = await run.io_bound(
                load_page, self.repository.list_logs, self.repository.count_logs, self.log_offset,
                self.selected.id)
        except DatabaseError as error:
            if request == self.log_request:
                self.log_message.text = str(error)
            return
        if request != self.log_request:
            return
        self.log_offset = offset
        with self.logs:
            pdf = list_print_tools(self, self.repository.database, 'group', self.selected.id)
            for entry in entries[:PAGE_SIZE]:
                open_log = lambda log_id=entry.id: self.open_editor(log=True, log_id=log_id)
                with ui.row().classes(
                        'w-full items-center justify-between border rounded-xl p-4 cursor-pointer hover:bg-slate-50 focus-visible:outline'
                ).props('role=button tabindex=0 aria-label="일지 열기"').on('click', open_log).on(
                        'keydown.enter.self.prevent', open_log).on('keydown.space.self.prevent', open_log):
                    with ui.column().classes('gap-1'):
                        ui.label(entry.title).classes('font-semibold')
                        ui.label(f'{entry.starts_at.astimezone(KST):%Y.%m.%d %H:%M} · {STATUSES[entry.status]} · {entry.duration_minutes}분').classes('text-sm text-slate-500')
                    with ui.row().classes('items-center gap-2 flex-nowrap shrink-0'):
                        pdf.row(entry.id)
                        delete_button(self.repository.database, 'group_log', lambda entry=entry: entry, self.after_log_deleted, blocked=lambda: self.editor_open, icon_only=True)

        self.log_message.text = f'이 페이지에 {min(len(entries), PAGE_SIZE)}건 · 한국 표준시' if entries else '등록된 집단 상담 일지가 없습니다.'
        self.page_label.text = f'{self.log_offset // PAGE_SIZE + 1}페이지/{pages}페이지'
        self.previous.set_enabled(self.log_offset > 0)
        self.next.set_enabled(self.log_offset // PAGE_SIZE + 1 < pages)

    async def open_editor(self, *, edit_group: bool = False, log: bool = False, log_id: int | None = None) -> None:
        if self.editor_open or ((edit_group or log) and self.selected is None):
            return
        self.editor_open = True
        group = self.selected if edit_group or log else None
        dialog = None
        try:
            entry = await run.io_bound(self.repository.get_log, log_id) if log_id is not None else None
            if log_id is not None and (entry is None or entry.group_id != group.id):
                ui.notify('이 집단의 상담 일지를 찾을 수 없습니다.', type='warning')
                return
            student_options = {}
            if not log:
                offset = 0
                while True:
                    students = await run.io_bound(self.students.list, limit=1000, offset=offset)
                    student_options.update({student.id: f'{student.name} · {student.grade}학년 {student.classroom}반 · 번호 {student.student_number or "미입력"}' for student in students})
                    if len(students) < 1000:
                        break
                    offset += len(students)
            fields = {}
            attendance_table = None
            saving = False
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-5xl p-6 gap-4'):
                    ui.label(('집단 상담 일지 수정' if entry else '새 집단 상담 일지') if log else ('집단 정보 수정' if group else '새 집단 상담')).classes('text-2xl font-bold')
                    if log:
                        ui.label(group.name).classes('text-slate-500')
                        local_start = entry.starts_at.astimezone(KST) if entry else datetime.now(KST).replace(second=0, microsecond=0)
                        with ui.grid(columns=4).classes('w-full gap-4'):
                            fields['starts_on'] = ui.date_input('상담 날짜', value=local_start.date().isoformat()).props('outlined').classes('w-full min-w-0')
                            fields['starts_time'] = time_input('시작 시각 (한국 시각)', value=local_start.time().isoformat()).props('outlined').classes('w-full min-w-0')
                            fields['duration_minutes'] = ui.number('상담 시간 (분)', value=entry.duration_minutes if entry else default_duration_minutes(self.repository.database, fallback=50), min=1, max=1440, step=1).props('outlined').classes('w-full min-w-0')
                            fields['status'] = ui.select(STATUSES, label='상담 상태', value=entry.status if entry else 'scheduled').props('outlined').classes('w-full min-w-0')
                        ui.label('참여 학생 출석 및 참여 태도').classes('font-semibold')
                        attendance_rows = ([row.model_dump() for row in entry.attendance]
                                           if entry and entry.attendance else [
                                               dict(student_id=student_id, name=label, attended=False, attitude='')
                                               for student_id, label in zip(group.student_ids, group.participant_labels)
                                           ])
                        attendance_table = ui.table(columns=[
                            dict(name=key, label=label, field=key, align='left',
                                 style='width: 1%; white-space: nowrap' if key != 'attitude' else 'width: 100%',
                                 headerStyle='width: 1%; white-space: nowrap' if key != 'attitude' else 'width: 100%')
                            for key, label in [('name', '이름'), ('attended', '출석'), ('attitude', '참여 태도')]
                        ], rows=attendance_rows, row_key='student_id').classes('w-full').props(
                            'flat bordered wrap-cells hide-bottom no-data-label="집단 정보에서 참여 학생을 먼저 등록해 주세요"')
                        attendance_table.add_slot('body-cell-attended', '''
                            <q-td :props="props" auto-width>
                                <q-checkbox v-model="props.row.attended"
                                    :aria-label="props.row.name + ' 출석'"
                                    @update:model-value="value => $parent.$emit('attendance_change', {student_id: props.row.student_id, field: 'attended', value})" />
                            </q-td>
                        ''')
                        attendance_table.add_slot('body-cell-attitude', '''
                            <q-td :props="props" style="min-width: 240px; width: 100%">
                                <q-input v-model="props.row.attitude" outlined dense autogrow
                                    type="textarea" maxlength="2000" placeholder="참여 태도를 입력하세요"
                                    :aria-label="props.row.name + ' 참여 태도'"
                                    @update:model-value="value => $parent.$emit('attendance_change', {student_id: props.row.student_id, field: 'attitude', value})" />
                            </q-td>
                        ''')

                        def update_attendance(event):
                            if saving:
                                return
                            args = event.args
                            if args.get('field') not in ('attended', 'attitude'):
                                return
                            for row in attendance_table.rows:
                                if row['student_id'] == args.get('student_id'):
                                    row[args['field']] = args['value']
                                    break

                        attendance_table.on('attendance_change', update_attendance)
                        ui.label('상담 내용').classes('font-semibold')
                        fields['content_html'] = ui.editor(value=clean_html(entry.content_html) if entry else '').classes('w-full').props("""min-height=320px :toolbar='[[{"label": "머릿말", "list": "no-icons", "options": ["p", "h1", "h2", "h3"]}], ["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
                        fields['follow_up'] = ui.textarea('후속 조치', value=entry.follow_up if entry else '').props('outlined maxlength=20000').classes('w-full')
                    else:
                        fields['name'] = ui.input('집단명', value=group.name if group else '').props(
                            'outlined maxlength=200').classes('w-full')
                        with ui.grid().classes('w-full gap-4').style('grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) minmax(0, 1fr)'):
                            fields['facilitator'] = ui.input('진행자', value=group.facilitator if group else '').props('outlined maxlength=100').classes('w-full min-w-0')
                            fields['period'] = ui.date_input('운영 기간 *', range_input=True, value=group.period if group else '').props('outlined required').classes('w-full min-w-0')
                            fields['counseling_area'] = ui.select(['학업', '진로', '학교폭력', '성격/대인관계', '기타'], label='상담 영역', value=group.counseling_area or None if group else None).props('outlined').classes('w-full min-w-0')
                        if group and group.participants:
                            fields['participants'] = ui.textarea('기존 참여자 메모', value=group.participants).props(
                                'outlined maxlength=20000').classes('w-full')
                        fields['purpose'] = ui.textarea('상담 목표', value=group.purpose if group else '').props(
                            'outlined maxlength=20000').classes('w-full')
                        fields['student_ids'] = ui.select(student_options, label='참여 학생', multiple=True,
                                                         value=list(group.student_ids) if group else [], with_input=True).props(
                            'outlined use-chips').classes('w-full')
                        ui.label('연결한 학생의 타임라인에 이 집단의 모든 상담 일지가 표시됩니다.').classes('text-sm text-slate-500')
                        fields['notes'] = ui.textarea('비고', value=group.notes if group else '').props(
                            'outlined maxlength=20000').classes('w-full')
                    message = ui.label().classes('text-red-700 text-sm')
                    with ui.row().classes('w-full items-center'):
                        if log:
                            files = attachment_button(self.repository.database, 'group_log', entry.id if entry else None)
                        ui.space()
                        cancel_button = ui.button('취소').props('flat')
                        save_button = ui.button('저장', icon='save')
            def form_data():
                data = {key: field.value for key, field in fields.items()}
                if attendance_table is not None:
                    data['attendance'] = attendance_table.rows
                return deepcopy(data)

            original = form_data()

            async def cancel():
                if saving:
                    return
                if (log and files.pending) or original != form_data():
                    with ui.dialog().props('persistent') as confirm, ui.card():
                        ui.label('저장하지 않은 내용을 버릴까요?')
                        ui.button('계속 작성', on_click=lambda: confirm.submit(False))
                        ui.button('변경 내용 버리기', on_click=lambda: confirm.submit(True))
                    discard = await confirm
                    confirm.delete()
                    if not discard:
                        return
                dialog.submit(None)

            async def save():
                nonlocal saving
                if saving:
                    return
                data = form_data()
                try:
                    if log:
                        data['starts_at'] = datetime.combine(
                            date.fromisoformat(data.pop('starts_on')), parse_time(data.pop('starts_time')))
                        if data['starts_at'].tzinfo is not None:
                            raise ValueError('한국 시각을 입력하세요.')
                        data['starts_at'] = data['starts_at'].replace(tzinfo=KST)
                        data['content_html'] = clean_html(data['content_html'] or '')
                        data['title'] = entry.title if entry else group.name
                        value = GroupLogInput(group_id=group.id, **data)
                    else:
                        data['student_ids'] = data.get('student_ids') or []
                        data['period'] = (data.get('period') or '').strip()
                        if not data['period']:
                            message.text = '운영 기간을 입력해 주세요. 학년도는 운영 시작일 기준으로 자동 계산됩니다.'
                            return
                        data['counseling_area'] = data.get('counseling_area') or ''
                        value = GroupCounselingInput(**data)
                except (ValueError, TypeError):
                    message.text = ('날짜·시각, 상담 시간(1~1440분)과 입력 길이를 확인해 주세요.' if log else
                                    '집단명과 입력 길이를 확인해 주세요. 운영 기간은 YYYY-MM-DD 또는 YYYY-MM-DD - YYYY-MM-DD 형식이며 종료일은 시작일 이후여야 합니다.')
                    return
                saving = True
                if attendance_table is not None:
                    attendance_table.props('inert')
                for field in (*fields.values(), save_button, cancel_button):
                    field.disable()
                try:
                    if log:
                        saved = await files.save_record(self.repository.save_log, value, log_id)
                    else:
                        saved = await run.io_bound(self.repository.save, value, group.id if group else None)
                    dialog.submit(saved)
                except DatabaseError as error:
                    message.text = str(error)
                finally:
                    saving = False
                    if attendance_table is not None:
                        attendance_table.props(remove='inert')
                    for field in (*fields.values(), save_button, cancel_button):
                        field.enable()

            save_button.on_click(save)
            cancel_button.on_click(cancel)
            saved = await dialog
            if saved:
                ui.notify('저장했습니다.', type='positive')
                if log:
                    if self.selected and self.selected.id == group.id:
                        self.log_offset = 0
                        await self.load_logs()
                else:
                    await self.load_groups()
                    if group is None or (self.selected and self.selected.id == group.id):
                        await self.select_group(saved.id)
                if self.on_saved:
                    await self.on_saved()
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()
