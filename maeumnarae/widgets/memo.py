"""인스턴스별 서식 있는 메모. 변경 즉시 현재 암호화 DB에 저장한다."""

from nicegui import ui

from maeumnarae.core.database import DatabaseError


class Memo:
    kind = 'memo'
    title = '메모'
    icon = 'edit_note'
    default_height = 430

    def __init__(self, home, teachers, instance_id=None, on_change=None):
        self.repository = home
        self.instance_id = instance_id or 'memo'
        self.loaded = False
        self.loading = False

    def build(self):
        ui.add_css('''
            .memo-editor { display: flex; flex-direction: column; flex: 1 1 0%;
                width: 100%; min-width: 0; min-height: 0; overflow: hidden; }
            .memo-editor .q-editor__toolbars-container { flex: 0 0 auto; max-height: 50%; overflow: auto; }
            .memo-editor .q-editor__content { flex: 1 1 0%; min-height: 0 !important;
                overflow: auto; overflow-wrap: anywhere; }
        ''')
        self.editor = ui.editor(placeholder='메모를 입력하세요.', on_change=self.changed).classes('memo-editor').props("""
            min-height=0
            :toolbar='[["bold", "italic", "underline", "strike"],
                       ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'
        """.replace("\n", " "))
        self.editor.disable()
        with ui.row().classes('w-full shrink-0 items-center justify-between gap-2'):
            self.status = ui.label('메모를 불러오는 중입니다…').classes('text-xs text-slate-500')
            self.retry = ui.button('다시 불러오기', icon='refresh', on_click=self.retry_action).props('flat dense')
            self.retry.set_visibility(False)
        ui.timer(0, self.load, once=True)

    def load(self):
        self.loading = True
        try:
            self.editor.value = self.repository.note(self.instance_id)
            self.loaded = True
            self.editor.enable()
            self.status.text = '자동 저장됩니다.'
            self.retry.set_visibility(False)
            if self.instance_id in self.repository.note_drafts:
                self.status.text = '저장하지 못한 메모가 있습니다. 다시 저장해 주세요.'
                self.retry.text = '다시 저장'
                self.retry.set_visibility(True)
        except (DatabaseError, ValueError) as error:
            self.status.text = str(error)
            self.retry.set_visibility(True)
        finally:
            self.loading = False

    def changed(self, event):
        if self.loaded and not self.loading:
            self.save(event.value or '')

    def save(self, content):
        # DB 저장을 동기 작업으로 처리해 배치 재구성 전에 변경을 확정한다.
        self.repository.note_drafts[self.instance_id] = content
        try:
            self.repository.save_note(self.instance_id, content)
            self.status.text = '저장됨'
            self.retry.set_visibility(False)
        except (DatabaseError, ValueError) as error:
            self.status.text = f'저장 실패: {error}'
            self.retry.text = '다시 저장'
            self.retry.set_visibility(True)

    def retry_action(self):
        if self.loaded:
            self.save(self.editor.value or '')
        else:
            self.load()
