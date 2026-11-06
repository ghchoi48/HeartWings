"""AI 전체 설정, 모델 관리와 저장하지 않는 테스트 생성 화면."""
import asyncio
from pathlib import Path

from nicegui import ui, background_tasks

from maeumnarae.services.ai.models import catalog, supports_reasoning
from maeumnarae.services.ai.types import AIError, GenerationRequest
from maeumnarae.views.settings_card import settings_card
from maeumnarae.views.ai_harness_view import AIHarnessView


def size_label(size):
    return f'{size / 1024**3:.2f} GiB'


class AISettingsView:
    def __init__(self, service, database):
        self.service, self.database = service, database
        self.client = ui.context.client
        self.session = self.client.id
        self.syncing = False
        self.snapshot = None
        self.response = ''
        self.closed = False
        self.sending = False
        self.chat_revision = 0
        self.lock_cleared = False

    async def action(self, operation):
        try:
            return await operation
        except AIError as error:
            if not self.closed:
                ui.notify(str(error), type='negative')
        except (OSError, ValueError):
            ui.notify('파일 또는 설정을 처리하지 못했습니다. 경로와 권한을 확인해 주세요.', type='negative')
        except asyncio.CancelledError:
            return None
        finally:
            if not self.closed:
                self.refresh()

    def build(self):
        self.service.attach(self.session, lambda: not self.database.is_locked)
        self.client.on_connect(self.connect)
        self.client.on_disconnect(self.disconnect)
        self.client.on_delete(self.delete)
        self.build_recommended_dialog()
        with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-2 gap-6 items-start'):
            with ui.column().classes('w-full min-w-0 gap-6'):
                with settings_card('AI 사용', 'auto_awesome',
                                   '입력과 응답은 이 컴퓨터에서 처리하며 저장하지 않습니다. 모델 다운로드에는 인터넷을 사용합니다.', '즉시 적용'):
                    self.toggle = ui.switch('AI 기능 전체 사용', on_change=self.toggle_changed)
                    self.state = ui.label().classes('font-semibold')
                    self.error = ui.label().classes('text-red-700 whitespace-pre-wrap')
                    if not self.service.runtime.supported:
                        ui.label('Windows x64 및 Apple Silicon Mac에서 사용할 수 있습니다.')
                with settings_card('사용할 모델', 'memory', '등록한 모델 중 하나를 선택하세요. 첫 생성 요청 때 모델을 로드합니다.',
                                   header_actions=self.build_model_actions):
                    self.selection = ui.select({}, label='사용할 모델', on_change=self.selection_changed).props('outlined clearable').classes('w-full')
                    self.reasoning_toggle = ui.switch('추론 모드', on_change=self.reasoning_changed)
                    self.reasoning_hint = ui.label().classes('text-sm text-slate-500')
                    ui.button('로컬 GGUF 등록', icon='folder_open', on_click=self.pick_file)
                    self.model_list = ui.column().classes('w-full gap-3')
            with ui.column().classes('w-full min-w-0'):
                with ui.tabs().classes('w-full') as tabs:
                    chat_tab = ui.tab('작동 확인')
                    harness_tab = ui.tab('작업 양식')
                with ui.tab_panels(tabs, value=chat_tab).classes('w-full bg-transparent'):
                    with ui.tab_panel(chat_tab).classes('p-0'):
                        self.build_chat()
                    with ui.tab_panel(harness_tab).classes('p-0'):
                        self.harness = AIHarnessView(self)
                        self.harness.build()
                self.task_tabs = tabs
                tabs.on_value_change(lambda e: self.harness.leave() if e.value != '작업 양식' else None)
        self.unsubscribe = self.service.subscribe(self.refresh)
        self.guard_timer = ui.timer(.5, self.check_lock)
        self.refresh()

    def build_model_actions(self):
        self.recommended_button = ui.button('추천 모델', icon='download',
                                           on_click=self.recommended_dialog.open).props('outline')

    def build_recommended_dialog(self):
        with ui.dialog() as self.recommended_dialog:
            with ui.card().classes('w-full max-w-2xl max-h-[85vh] overflow-auto rounded-2xl p-6 gap-4'):
                with ui.row().classes('w-full items-center justify-between'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('download').classes('text-primary')
                        ui.label('추천 모델').classes('text-xl font-bold')
                    ui.button(icon='close', on_click=self.recommended_dialog.close).props(
                        'flat round dense aria-label="추천 모델 닫기"')
                ui.label('모델은 직접 다운로드한 뒤 선택하세요. 권장 메모리는 목표 환경이며 실제 사용량은 달라질 수 있습니다.').classes('text-sm text-slate-500')
                self.recommended_status = ui.label().classes('text-sm text-slate-600').props('role=status')
                self.download_buttons = {}
                for item in catalog():
                    with ui.column().classes('w-full border rounded-lg p-4 gap-2'):
                        ui.label(item.name).classes('font-semibold')
                        ui.label(item.description).classes('text-sm')
                        ui.label(f'{size_label(item.size)} · 권장 메모리 {item.memory_gb}GB').classes('text-sm text-slate-500')
                        ui.link(item.license, item.license_url, new_tab=True)
                        self.download_buttons[item.id] = ui.button('다운로드', icon='download',
                            on_click=lambda item=item: self.action(self.service.download(self.session, item.id)))
                self.progress = ui.linear_progress(value=0).classes('w-full')
                self.progress_label = ui.label().classes('text-sm')
                self.download_cancel = ui.button('다운로드 취소', on_click=lambda: self.action(self.service.cancel_download(self.session))).props('flat')
                ui.label('창을 닫아도 다운로드는 계속됩니다. 이 창을 다시 열어 진행 상태를 확인하거나 취소할 수 있습니다.').classes('text-xs text-slate-500')
                with ui.row().classes('w-full justify-end'):
                    ui.button('닫기', on_click=self.recommended_dialog.close).props('flat')

    def build_chat(self):
        ui.add_css('''
            .ai-chat-content, .ai-chat-content .q-message-text-content,
            .ai-chat-content .ai-message-text {
                -webkit-user-select: text !important;
                user-select: text !important;
            }
            .ai-chat-content .ai-message-text { cursor: text; }
        ''')
        with ui.card().classes(
            'w-full min-w-0 rounded-2xl border border-slate-200 shadow-sm bg-white '
            'p-0 gap-0 overflow-hidden lg:sticky lg:top-0'
        ):
            with ui.column().classes('w-full gap-2 p-5 border-b border-slate-200'):
                with ui.row().classes('w-full items-center justify-between'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('chat_bubble_outline', size='24px').classes('text-primary')
                        ui.label('작동 확인').classes('text-xl font-bold text-slate-800')
                    self.clear_button = ui.button('대화 지우기', icon='delete_sweep',
                                                  on_click=self.clear_text).props('flat dense')
                self.chat_model = ui.label().classes('text-sm font-medium text-slate-600')
                self.chat_state = ui.label().classes('text-xs text-slate-500').props('role=status aria-live=polite')
            with ui.scroll_area().classes('w-full h-[420px] lg:h-[480px] bg-slate-50') as self.chat_scroll:
                self.messages = ui.column().classes('ai-chat-content w-full min-w-0 gap-4 p-4')
                with self.messages:
                    self.build_empty_chat()
            with ui.column().classes('w-full gap-3 p-4 border-t border-slate-200'):
                self.prompt = ui.textarea(placeholder='AI에게 테스트 메시지를 보내세요').props(
                    'outlined rows=2 maxlength=12000 aria-label="테스트 메시지"'
                ).classes('w-full')
                self.prompt.on('keydown', self.generate, js_handler=r'''
                    (e) => {
                        if (e.code === 'ShiftLeft') {
                            e.target.dataset.leftShift = 'true';
                            return;
                        }
                        if (!e.shiftKey) delete e.target.dataset.leftShift;
                        if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
                        e.preventDefault();
                        if (e.repeat) return;
                        if (e.shiftKey && e.target.dataset.leftShift === 'true') {
                            const input = e.target;
                            const start = input.selectionStart;
                            const end = input.selectionEnd;
                            if (input.maxLength >= 0 &&
                                input.value.length - (end - start) + 1 > input.maxLength) return;
                            input.setRangeText('\n', start, end, 'end');
                            input.dispatchEvent(new Event('input', {bubbles: true}));
                        } else {
                            emit();
                        }
                    }
                ''')
                self.prompt.on('keyup', js_handler=
                               "(e) => { if (e.code === 'ShiftLeft') delete e.target.dataset.leftShift; }")
                self.prompt.on('focusout', js_handler=
                               '(e) => { delete e.target.dataset.leftShift; }')
                with ui.row().classes('w-full items-center justify-between gap-2'):
                    ui.label('Enter로 전송 · 왼쪽 Shift + Enter로 줄바꿈').classes('text-xs text-slate-500')
                    with ui.row().classes('gap-2'):
                        self.stop_button = ui.button('생성 중지', icon='stop', on_click=lambda:
                            self.action(self.service.cancel(self.session))).props('flat')
                        self.generate_button = ui.button('보내기', icon='send', on_click=self.generate)
                ui.label('각 메시지는 독립적으로 응답합니다. 대화는 저장되지 않습니다. '
                         '학생 정보나 실제 상담 기록을 입력하지 마세요.').classes('text-xs text-slate-500')

    def build_empty_chat(self):
        with ui.column().classes('w-full items-center text-center py-10 gap-3') as self.empty_chat:
            ui.icon('forum', size='36px').classes('text-primary')
            ui.label('로컬 AI와 대화를 시작해 보세요').classes('font-semibold text-slate-700')
            ui.label('AI 사용을 켜고 모델을 선택한 뒤 메시지를 보내세요.').classes('text-sm text-slate-500')
        # 응답은 텍스트로만 표시하며 HTML이나 외부 이미지를 실행하지 않는다.
        self.output = ui.label('').classes('hidden')

    async def check_lock(self):
        if self.closed:
            return
        if self.database.is_locked:
            # 앱 잠금 경로에서 이미 detach했어도 화면의 임시 내용은 지운다.
            if not self.lock_cleared:
                self.lock_cleared = True
                self.clear_text()
                self.harness.clear()
            if self.session in self.service.sessions:
                await self.service.detach(self.session, lock=True)
        else:
            self.lock_cleared = False

    def clear_text(self):
        self.chat_revision += 1
        self.response = ''
        with self.client:
            self.messages.clear()
            with self.messages:
                self.build_empty_chat()
            self.prompt.set_value('')

    def leave(self):
        """설정 화면을 숨길 때도 시험 데이터와 늦은 응답을 무효화한다."""
        if self.closed:
            return
        self.clear_text()
        self.harness.clear()
        self.cancel_on_leave()

    def cancel_on_leave(self):
        task = self.service.generation
        if task is None or self.service.owner != self.session:
            return
        async def cancel():
            if self.service.generation is task and self.session in self.service.sessions:
                await self.action(self.service.cancel(self.session))
        background_tasks.create(cancel())

    def connect(self):
        self.service.attach(self.session, lambda: not self.database.is_locked)
        self.refresh()

    async def disconnect(self):
        if self.closed:
            return
        self.clear_text()
        self.harness.clear()
        await self.service.detach(self.session)

    async def delete(self):
        if self.closed:
            return
        self.closed = True
        self.chat_revision += 1
        self.response = ''
        self.harness.result = None
        self.harness.revision += 1
        if not self.client.is_deleted:
            self.harness.clear()
            self.messages.clear()
            self.prompt.set_value('')
        self.unsubscribe()
        self.guard_timer.deactivate()
        await self.service.detach(self.session)

    def toggle_changed(self, event):
        if not self.syncing and not self.closed:
            return self.action(self.service.set_enabled(self.session, bool(event.value)))

    def reasoning_changed(self, event):
        if not self.syncing and not self.closed:
            return self.action(self.service.set_reasoning(self.session, bool(event.value)))

    def selection_changed(self, event):
        if not self.syncing and not self.closed:
            return self.action(self.service.select_model(self.session, event.value))

    def refresh(self):
        if self.closed:
            return
        with self.client:
            self.syncing = True
            try:
                status = self.service.status
                authorized = not self.database.is_locked and self.session in self.service.sessions
                if not authorized:
                    self.clear_text()
                self.toggle.set_value(self.service.settings.enabled)
                self.toggle.set_enabled(authorized and self.service.runtime.supported)
                backend = getattr(self.service.runtime, 'backend', '')
                self.state.set_text(status.state + (f' · {backend}' if self.service.runtime.model_id else ''))
                self.error.set_text(status.error)
                self.recommended_button.set_enabled(authorized)
                if not authorized:
                    self.recommended_dialog.close()
                self.recommended_status.set_text(status.error or (
                    'AI 사용을 켜면 모델을 다운로드할 수 있습니다.' if not self.service.settings.enabled
                    else '모델을 다운로드하고 있습니다…' if status.download_id else '다운로드할 모델을 선택하세요.'))
                self.selection.set_options({key: record.name for key, record in self.service.models.records.items()},
                                           value=self.service.settings.selected_model_id)
                self.selection.set_enabled(authorized)
                for key, button in self.download_buttons.items():
                    button.set_enabled(authorized and self.service.settings.enabled and self.service.runtime.supported
                                       and not status.download_id and key not in self.service.models.records)
                self.progress.set_visibility(bool(status.download_id))
                progress = min(1, max(0, status.downloaded / status.total)) if status.total else 0
                self.progress.set_value(progress)
                self.progress_label.set_text(f'{progress:.1%}' if status.download_id else '')
                self.download_cancel.set_visibility(bool(status.download_id))
                self.download_cancel.set_enabled(authorized)
                selected = self.service.models.records.get(self.service.settings.selected_model_id)
                reasoning_supported = supports_reasoning(selected)
                self.reasoning_toggle.set_value(self.service.settings.reasoning_enabled and reasoning_supported)
                self.reasoning_toggle.set_enabled(authorized and self.service.runtime.supported and reasoning_supported)
                self.reasoning_hint.set_text(
                    '답변 전에 더 깊이 생각합니다. 응답 시간이 길어질 수 있으며 변경은 다음 메시지부터 적용됩니다.'
                    if reasoning_supported else 'EXAONE 4 또는 Qwen3 모델을 선택하면 추론 모드를 설정할 수 있습니다.')
                self.chat_model.set_text(selected.name if selected else '선택된 모델 없음')
                self.chat_state.set_text(status.error or status.state)
                self.prompt.set_enabled(authorized and not self.sending)
                self.clear_button.set_enabled(authorized and not self.sending)
                self.generate_button.set_enabled(not self.sending and authorized and self.service.settings.enabled and self.service.runtime.supported
                                                 and bool(self.service.settings.selected_model_id) and not self.service.generation)
                self.stop_button.set_enabled(authorized and self.service.owner == self.session)
                self.stop_button.set_visibility(self.service.owner == self.session)
                snapshot = tuple(self.service.models.records.values())
                if snapshot != self.snapshot:
                    self.snapshot = snapshot
                    self.model_list.clear()
                    with self.model_list:
                        if not snapshot:
                            ui.label('등록된 모델이 없습니다. 추천 모델을 다운로드하거나 로컬 GGUF를 등록하세요.').classes('text-sm text-slate-500')
                        for record in snapshot:
                            with ui.row().classes('w-full items-center justify-between'):
                                with ui.column().classes('gap-1 min-w-0 flex-1'):
                                    ui.label(record.name).classes('font-semibold')
                                    ui.label(f'{size_label(record.size)} · ' + ('로드 검증 완료' if record.verified else '로드 전 미검증')).classes('text-sm')
                                    ui.label(record.path).classes('text-xs break-all text-slate-500')
                                ui.button('삭제' if record.managed else '등록 해제', icon='delete_outline',
                                          on_click=lambda record=record: self.confirm_remove(record)).props('flat color=negative')
            finally:
                self.syncing = False
                if hasattr(self, 'harness'):
                    self.harness.refresh()

    async def confirm_remove(self, record):
        with ui.dialog() as dialog, ui.card():
            ui.label(f'{record.name}: ' + ('다운로드한 파일을 삭제할까요?' if record.managed else '등록을 해제할까요? 원본 파일은 유지합니다.'))
            with ui.row():
                ui.button('취소', on_click=lambda: dialog.submit(False)).props('flat')
                ui.button('삭제' if record.managed else '등록 해제', on_click=lambda: dialog.submit(True)).props('color=negative')
        if await dialog:
            await self.action(self.service.remove_model(self.session, record.id))
        dialog.delete()

    async def generate(self):
        prompt = (self.prompt.value or '').strip()
        if self.sending or not prompt:
            return
        try:
            self.service.authorize(self.session)
        except AIError as error:
            ui.notify(str(error), type='negative')
            return
        if (not self.service.settings.enabled or not self.service.runtime.supported
                or not self.service.settings.selected_model_id or self.service.generation):
            ui.notify('AI 사용과 모델 선택을 확인하고 진행 중인 생성이 끝난 뒤 보내 주세요.', type='warning')
            return
        self.sending = True
        self.response = ''
        revision = self.chat_revision
        self.empty_chat.set_visibility(False)
        with self.messages:
            with ui.chat_message(name='나', sent=True).props(
                'bg-color=primary text-color=white'
            ).classes('w-full min-w-0'):
                ui.label(prompt).classes('ai-message-text whitespace-pre-wrap break-words max-w-full')
            with ui.chat_message(name='AI', sent=False).props(
                'bg-color=white text-color=grey-9'
            ).classes('w-full min-w-0'):
                # 추론과 답변 모두 텍스트로 표시하며 모델의 HTML은 실행하지 않는다.
                with ui.column().classes('w-full min-w-0 gap-2'):
                    with ui.column().classes(
                        'w-full min-w-0 gap-2 rounded-lg border border-slate-200 p-3'
                    ) as reasoning_panel:
                        ui.label('생각 과정').classes('ai-message-text text-sm font-medium text-slate-600')
                        reasoning_output = ui.label('').classes(
                            'ai-message-text whitespace-pre-wrap break-words text-sm text-slate-600')
                    reasoning_panel.set_visibility(False)
                    self.output = ui.label('응답을 준비하고 있습니다…').classes(
                        'ai-message-text whitespace-pre-wrap break-words max-w-full')
        self.prompt.set_value('')
        self.chat_scroll.scroll_to(percent=1)
        self.refresh()

        reasoning_text = ''

        def emit(event):
            nonlocal reasoning_text
            if (not self.closed and revision == self.chat_revision
                    and self.session in self.service.sessions and not self.database.is_locked):
                if event.kind == 'reasoning':
                    first_chunk = not reasoning_text
                    reasoning_text += event.text
                    reasoning_output.set_text(reasoning_text)
                    if first_chunk and reasoning_text:
                        reasoning_panel.set_visibility(True)
                    if not self.response:
                        self.output.set_text('생각하고 있습니다…')
                elif event.kind == 'text':
                    self.response += event.text
                    self.output.set_text(self.response)
                    self.chat_scroll.scroll_to(percent=1)
        try:
            await self.action(self.service.generate(self.session, GenerationRequest(prompt), emit))
        finally:
            self.sending = False
            if not self.closed:
                if revision == self.chat_revision and not self.response:
                    self.output.set_text('응답을 받지 못했습니다. AI 상태를 확인하거나 다시 보내 주세요.')
                self.refresh()

    async def pick_file(self):
        try:
            self.service.authorize(self.session)
        except AIError as error:
            ui.notify(str(error), type='negative')
            return
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-3xl'):
            ui.label('이 컴퓨터의 GGUF 파일 선택').classes('text-lg font-semibold')
            location = ui.input('폴더 또는 GGUF 경로', value=str(Path.home())).props('outlined').classes('w-full')
            entries = ui.column().classes('w-full max-h-80 overflow-auto')
            async def browse(path):
                try:
                    self.service.authorize(self.session)
                    path = Path(path).expanduser().resolve(strict=True)
                    if path.is_file():
                        record = await self.action(self.service.register_model(self.session, path))
                        if record:
                            dialog.close()
                        return
                    def listing():
                        return sorted((p for p in path.iterdir() if p.is_dir() or p.suffix.lower() == '.gguf'),
                                      key=lambda p: (not p.is_dir(), p.name.lower()))[:500]
                    children = await asyncio.to_thread(listing)
                    self.service.authorize(self.session)
                    location.set_value(str(path))
                    entries.clear()
                    with entries:
                        ui.button('상위 폴더', icon='arrow_upward', on_click=lambda: browse(path.parent)).props('flat')
                        for child in children:
                            ui.button(child.name, icon='folder' if child.is_dir() else 'description',
                                      on_click=lambda child=child: browse(child)).props('flat align=left').classes('w-full')
                except (OSError, AIError):
                    ui.notify('경로를 열 수 없습니다. DB 잠금과 파일 권한을 확인해 주세요.', type='negative')
            ui.button('경로 열기 / 파일 등록', on_click=lambda: browse(location.value))
            ui.button('닫기', on_click=dialog.close).props('flat')
        dialog.open()
        await browse(Path.home())
