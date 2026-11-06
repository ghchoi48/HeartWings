"""설정 전용 양식 편집기. 시험 입력과 결과는 메모리에만 존재한다."""
import asyncio
import json
import uuid
from nicegui import ui
from maeumnarae.services.ai.types import AIError
from maeumnarae.services.ai.harness.store import MAX_BYTES, parse_definition


class AIHarnessView:
    def __init__(self, parent):
        self.parent = parent
        self.service = parent.service
        self.session = parent.session
        self.revision = 0
        self.running = False
        self.syncing = False
        self.result = None
        self.selected_id = next(iter(self.service.harnesses.defaults))
        self.data = self.service.harnesses.all[self.selected_id].model_dump()
        self.dialogs = []

    def authorize(self):
        self.service.authorize(self.session)

    def guarded(self, operation):
        if self.parent.closed or self.parent.client.is_deleted:
            return
        try:
            self.authorize()
            return operation()
        except AIError as error:
            ui.notify(str(error), type='negative')

    def build(self):
        with ui.column().classes('w-full gap-4'):
            ui.label('AI 작업 양식(하네스)').classes('text-xl font-bold')
            ui.label('작성 지침과 결과 항목을 정해 반복해서 사용하세요. 학생 개인정보를 양식 지침에 넣지 마세요.').classes('text-sm text-slate-600')
            self.error = ui.label(self.service.harnesses.error).classes('text-red-700')
            self.selection = ui.select({}, label='작업 양식', on_change=self.selection_changed).classes('w-full').props('outlined')
            with ui.row():
                ui.button('복제', icon='content_copy', on_click=lambda: self.guarded(self.duplicate))
                ui.button('저장', icon='save', on_click=lambda: self.guarded(self.save))
                ui.button('삭제', icon='delete_outline', on_click=self.delete)
                ui.button('가져오기', icon='upload', on_click=lambda: self.guarded(self.import_dialog))
                ui.button('내보내기', icon='download', on_click=lambda: self.guarded(self.export))
            self.editor = ui.column().classes('w-full gap-3')
            self.render_editor()
            with ui.expansion('고급 설정 · JSON 편집').classes('w-full'):
                ui.label('쉬운 편집기의 변경은 JSON에 반영됩니다. JSON을 수정한 뒤 적용하세요.').classes('text-sm')
                self.advanced = ui.textarea('양식 JSON').props('outlined rows=12').classes('w-full')
                ui.button('JSON 변경 적용', on_click=lambda: self.guarded(self.apply_json))
            self.sync_json()
            ui.separator()
            ui.label('시험 실행').classes('text-lg font-semibold')
            examples = self.service.harnesses.examples
            ui.select({i: v['name'] for i, v in enumerate(examples)}, label='가상 예시',
                      on_change=lambda e: self.note.set_value(examples[e.value]['note']) if e.value is not None else None).classes('w-full')
            self.note = ui.textarea('임시 상담 메모', placeholder='가상 메모로 시험해 보세요.').props('outlined rows=5 maxlength=12000').classes('w-full')
            ui.label('입력·응답은 저장되지 않으며 실제 상담일지에 반영되지 않습니다. 시험은 추론 모드를 끄고 실행합니다.').classes('text-xs text-slate-500')
            with ui.row():
                self.run_button = ui.button('시험 실행', icon='play_arrow', on_click=self.run)
                self.stop_button = ui.button('중지', icon='stop', on_click=self.stop)
                ui.button('시험 내용 지우기', on_click=self.clear_and_stop).props('flat')
            self.status = ui.label('').props('role=status aria-live=polite')
            self.results = ui.column().classes('w-full')
        self.refresh()

    def sync_json(self):
        if hasattr(self, 'advanced'):
            self.synced_json = json.dumps(self.data, ensure_ascii=False, indent=2)
            self.advanced.set_value(self.synced_json)

    def edit(self, target, key, value):
        target[key] = value
        self.sync_json()

    def render_editor(self):
        self.editor.clear()
        builtin = self.selected_id in self.service.harnesses.defaults
        with self.editor:
            if builtin:
                ui.label('기본 양식입니다. 복제하면 자유롭게 편집할 수 있습니다.').classes('text-sm text-primary')
            for key, label, multiline in [('name', '양식 이름', False), ('description', '설명', False),
                    ('instruction', '작성 지침', True), ('style', '문체', False)]:
                widget = (ui.textarea if multiline else ui.input)(label, value=self.data[key],
                    on_change=lambda e, key=key: self.edit(self.data, key, e.value))
                widget.props('outlined').classes('w-full').set_enabled(not builtin)
            for index, field in enumerate(self.data['fields']):
                with ui.card().classes('w-full border shadow-none'):
                    ui.input('출력 항목 이름', value=field['name'], on_change=lambda e, f=field:
                             self.edit(f, 'name', e.value)).classes('w-full').set_enabled(not builtin)
                    ui.textarea('항목 작성 지침', value=field['instruction'], on_change=lambda e, f=field:
                                self.edit(f, 'instruction', e.value)).props('rows=2').classes('w-full').set_enabled(not builtin)
                    ui.switch('원문 근거 확인', value=field['evidence_required'], on_change=lambda e, f=field:
                              self.edit(f, 'evidence_required', e.value)).set_enabled(not builtin)
                    with ui.row():
                        ui.button('위로', on_click=lambda i=index: self.move(i, -1)).props('flat dense').set_enabled(not builtin and index > 0)
                        ui.button('아래로', on_click=lambda i=index: self.move(i, 1)).props('flat dense').set_enabled(not builtin and index < len(self.data['fields']) - 1)
                        ui.button('항목 삭제', on_click=lambda i=index: self.remove_field(i)).props('flat dense').set_enabled(not builtin and len(self.data['fields']) > 1)
            ui.button('출력 항목 추가', icon='add', on_click=self.add_field).set_enabled(not builtin and len(self.data['fields']) < 8)

    def add_field(self):
        if len(self.data['fields']) < 8:
            self.data['fields'].append(dict(id='f_' + uuid.uuid4().hex, name='새 항목', instruction='', evidence_required=True))
            self.render_editor(); self.sync_json()

    def remove_field(self, index):
        if len(self.data['fields']) > 1:
            self.data['fields'].pop(index)
            self.render_editor(); self.sync_json()

    def move(self, index, offset):
        fields = self.data['fields']
        fields[index], fields[index + offset] = fields[index + offset], fields[index]
        self.render_editor(); self.sync_json()

    def definition(self):
        if self.advanced.value != self.synced_json:
            raise AIError('고급 설정의 JSON 변경을 먼저 적용하세요.')
        return parse_definition(json.dumps(self.data, ensure_ascii=False))

    def apply_json(self):
        definition = parse_definition(self.advanced.value or '')
        if self.selected_id in self.service.harnesses.defaults:
            raise AIError('기본 양식은 복제한 뒤 수정하세요.')
        if definition.id != self.selected_id:
            raise AIError('양식 ID는 변경할 수 없습니다. 새 양식은 가져오기 또는 복제로 추가하세요.')
        self.data = definition.model_dump()
        self.render_editor(); self.sync_json()
        ui.notify('JSON 변경을 편집기에 적용했습니다. 저장 또는 시험 실행을 선택하세요.')

    def selection_changed(self, event):
        if not self.syncing and not self.parent.closed:
            return self.select(event)

    async def select(self, event):
        if self.parent.closed:
            return
        key = event.value
        if key == self.selected_id or key not in self.service.harnesses.all:
            return
        original = self.service.harnesses.all.get(self.selected_id)
        if self.advanced.value != self.synced_json or (original and self.data != original.model_dump()):
            if not await self.confirm('저장하지 않은 양식 변경을 버리고 이동할까요?'):
                self.selection.set_value(self.selected_id)
                return
        self.guarded(lambda: self.load(key))

    def load(self, key):
        self.selected_id = key
        self.data = self.service.harnesses.all[key].model_dump()
        self.render_editor(); self.sync_json(); self.refresh()

    def save(self):
        self.service.save_harness(self.session, self.definition())
        ui.notify('작업 양식을 저장했습니다.')

    def duplicate(self):
        definition = self.service.duplicate_harness(self.session, self.definition())
        self.load(definition.id)

    async def confirm(self, message):
        with ui.dialog() as dialog, ui.card():
            ui.label(message)
            with ui.row():
                ui.button('취소', on_click=lambda: dialog.submit(False)).props('flat')
                ui.button('확인', on_click=lambda: dialog.submit(True))
        self.dialogs.append(dialog)
        try:
            return await dialog
        finally:
            self.dialogs.remove(dialog)
            dialog.delete()

    async def delete(self):
        key = self.selected_id
        if key in self.service.harnesses.defaults:
            ui.notify('기본 양식은 삭제할 수 없습니다.', type='warning')
            return
        if await self.confirm('이 작업 양식을 삭제할까요?'):
            def operation():
                self.service.delete_harness(self.session, key)
                self.load(next(iter(self.service.harnesses.defaults)))
            self.guarded(operation)

    def export(self):
        definition = self.definition()
        ui.download(definition.model_dump_json(indent=2).encode('utf-8'), filename='harness.json', media_type='application/json')

    def import_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label('양식 JSON 가져오기').classes('text-lg font-bold')
            raw = ui.textarea('JSON 붙여넣기').props('rows=8 outlined').classes('w-full')
            preview = ui.column().classes('w-full')
            candidate = [None]
            def inspect():
                candidate[0] = None
                preview.clear()
                definition = parse_definition(raw.value or '')
                candidate[0] = definition
                with preview:
                    ui.label(definition.name).classes('font-bold')
                    ui.label(definition.description)
                    ui.label('출력 항목: ' + ' → '.join(f.name for f in definition.fields))
                    ui.label('지침: ' + definition.instruction).classes('whitespace-pre-wrap')
                    ui.button('새 양식으로 추가', on_click=lambda: self.guarded(commit))
            def commit():
                if candidate[0] is not None:
                    definition = self.service.duplicate_harness(self.session, candidate[0])
                    self.load(definition.id)
                    dialog.close()
            async def upload(event):
                revision = self.revision
                try:
                    self.authorize()
                    if event.file.size() > MAX_BYTES:
                        raise AIError('양식 파일은 64 KiB 이하여야 합니다.')
                    content = await event.file.read()
                    self.authorize()
                    if revision != self.revision or self.parent.closed or dialog not in self.dialogs:
                        return
                    raw.set_value(content.decode('utf-8'))
                    inspect()
                except (AIError, UnicodeError):
                    ui.notify('양식 파일의 크기·UTF-8 인코딩·형식을 확인하세요.', type='negative')
            ui.upload(on_upload=upload, auto_upload=True, max_file_size=MAX_BYTES).props('accept=.json').classes('w-full')
            ui.button('미리 보기', on_click=lambda: self.guarded(inspect))
            ui.button('닫기', on_click=dialog.close).props('flat')
        self.dialogs.append(dialog)
        def cleanup():
            candidate[0] = None
            raw.set_value('')
            if dialog in self.dialogs:
                self.dialogs.remove(dialog)
            dialog.delete()
        dialog.on('hide', cleanup)
        dialog.open()

    def clear(self):
        self.revision += 1
        self.result = None
        self.note.set_value('')
        self.results.clear()
        self.status.set_text('')
        for dialog in tuple(self.dialogs):
            dialog.close()

    def leave(self):
        self.clear()
        if self.running:
            self.parent.cancel_on_leave()

    async def clear_and_stop(self):
        self.clear()
        await self.stop()

    async def stop(self):
        await self.parent.action(self.service.cancel(self.session))

    def refresh(self):
        if self.selected_id not in self.service.harnesses.all:
            self.selected_id = next(iter(self.service.harnesses.defaults))
            self.data = self.service.harnesses.all[self.selected_id].model_dump()
            self.render_editor()
            self.sync_json()
        self.syncing = True
        try:
            self.selection.set_options({k: v.name for k, v in self.service.harnesses.all.items()},
                                       value=self.selected_id)
        finally:
            self.syncing = False
        authorized = self.session in self.service.sessions and not self.parent.database.is_locked
        ready = authorized and self.service.settings.enabled and self.service.runtime.supported and bool(self.service.settings.selected_model_id)
        self.run_button.set_enabled(ready and not self.running and not self.service.generation)
        self.stop_button.set_enabled(authorized and self.service.owner == self.session)
        self.note.set_enabled(authorized and not self.running)

    async def run(self):
        if self.running:
            return
        try:
            self.authorize()
            definition = self.definition()
        except AIError as error:
            ui.notify(str(error), type='negative')
            return
        model = self.service.models.records.get(self.service.settings.selected_model_id)
        model_name = model.name if model else ''
        self.running = True
        revision = self.revision
        self.result = None
        self.results.clear()
        self.status.set_text('생성 및 검사 중…')
        self.refresh()
        try:
            result = await self.service.run_harness(self.session, definition, self.note.value or '')
            if self.parent.closed or revision != self.revision or self.parent.database.is_locked:
                return
            self.result = result
            self.status.set_text(f'{result.elapsed_seconds:.1f}초 · 재시도 {result.retries}회 · 형식 오류 {result.format_errors}회 · 근거/검토 알림 {len(result.issues)}개')
            with self.results:
                ui.label(f'{definition.name} · {model_name}').classes('font-semibold')
                ui.label('형식 검사 통과 · 내용 검토 필요' if result.format_valid else '형식 검사 실패').classes('font-bold')
                ui.label('인용 확인은 사실성 보장이 아닙니다. 생성 내용과 원문을 직접 비교하세요.').classes('text-sm')
                names = {f.id: f.name for f in definition.fields}
                for field in result.fields:
                    with ui.card().classes('w-full shadow-none border'):
                        ui.label(names[field.id]).classes('font-semibold')
                        ui.label(field.text).classes('whitespace-pre-wrap break-words')
                        for quote in field.evidence:
                            ui.label('근거: ' + quote).classes('text-sm whitespace-pre-wrap break-words')
                for issue in result.issues:
                    ui.label((names.get(issue.field_id, '') + ': ' if issue.field_id else '') + issue.message).classes('text-amber-800')
                with ui.expansion('JSON 원문').classes('w-full'):
                    ui.label(result.raw_json).classes('whitespace-pre-wrap break-all text-xs')
        except asyncio.CancelledError:
            if revision == self.revision and not self.parent.closed:
                self.status.set_text('시험 실행을 중지했습니다.')
        except AIError as error:
            if revision == self.revision and not self.parent.closed:
                self.status.set_text(str(error))
        finally:
            self.running = False
            if not self.parent.closed:
                self.refresh()
