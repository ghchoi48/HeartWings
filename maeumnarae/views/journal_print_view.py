"""공통 PDF 출력 대화상자와 목록 선택, 학년도 출력 UI."""
from dataclasses import replace
from datetime import datetime

from nicegui import run, ui

from maeumnarae.core.models import current_school_year
from maeumnarae.repositories.journal_print_repo import JournalPrintRepository
from maeumnarae.services.journal_print_models import PrintRequest, KINDS, STATUSES
from maeumnarae.services.reporting import KST
from maeumnarae.views.settings_card import settings_card

JOURNAL_PDF_VISIBLE = False


def journal_pdf_visible(kind):
    return kind in KINDS or JOURNAL_PDF_VISIBLE


def invalidate_prints(client=None):
    client = client if client is not None else ui.context.client
    client._journal_print_epoch = getattr(client, '_journal_print_epoch', 0) + 1


def live(element, epoch):
    return (not element.is_deleted and element.client.has_socket_connection and
            getattr(element.client, '_journal_print_epoch', 0) == epoch)


async def print_dialog(database, request, anchor, blocked=lambda: False):
    if blocked():
        ui.notify('작성 중인 내용을 저장한 후 PDF를 출력해 주세요.', type='warning')
        return
    epoch = getattr(anchor.client, '_journal_print_epoch', 0)
    with anchor.client.content:
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl p-6'):
            ui.label('일지 PDF 출력').classes('text-xl font-bold')
            mask = ui.checkbox('이름 가리기', value=request.mask_names)
            ui.label('이름 가리기를 켜면 학생 이름 대신 학생 ID를 표시합니다. 본문에 직접 작성한 이름은 자동으로 가려지지 않습니다. 비밀 메모와 첨부파일은 제외됩니다.').classes('text-sm text-slate-500')
            message = ui.label('일지 건수를 확인하는 중입니다…')
            generate = ui.button('PDF 생성 및 다운로드', icon='picture_as_pdf')
            generate.disable()
            ui.button('닫기', on_click=dialog.close).props('flat')
    dialog.open()
    busy = False
    snapshot = None
    closed = False

    def close():
        nonlocal closed, snapshot
        closed, snapshot = True, None
    dialog.on('hide', close)

    def valid():
        return not closed and live(anchor, epoch)

    def dismiss_stale():
        if closed or not live(anchor, epoch):
            dialog.close()
            timer.deactivate()
            if not busy:
                dialog.delete()
    timer = ui.timer(0.3, dismiss_stale)

    async def create():
        nonlocal busy, snapshot
        if busy or snapshot is None or not valid():
            return
        if blocked():
            message.text = '작성 중인 내용을 먼저 저장해 주세요.'
            return
        busy = True
        generate.disable()
        mask.disable()
        message.text = 'PDF를 생성하는 중입니다…'
        try:
            # 건수 확인 이후 삭제/수정도 반영한다. 오류가 있으면 부분 PDF를 전달하지 않는다.
            current = await run.io_bound(JournalPrintRepository(database).snapshot, request)
            if not valid():
                return
            if current != snapshot:
                snapshot = current
                message.text = '기록이 변경되었습니다. ' + counts_text(current) + ' 확인 후 다시 생성해 주세요.'
                return
            from maeumnarae.services.journal_pdf import build_pdf
            content = await run.io_bound(build_pdf, current, replace(request, mask_names=mask.value))
            # 생성 중 DB 잠금/교체도 확인한다.
            await run.io_bound(check_database, database)
            if not valid():
                return
            name = (f'마음나래_{request.school_year}학년도_전체일지.pdf' if request.school_year is not None else
                    f'마음나래_일지_{datetime.now(KST):%Y%m%d_%H%M%S}.pdf')
            ui.download.content(content, name, media_type='application/pdf')
            message.text = 'PDF를 다운로드했습니다. 파일을 열어 인쇄하세요.'
        except Exception:
            if valid():
                message.text = 'PDF를 만들지 못했습니다. DB 잠금 상태와 선택한 기록을 확인한 뒤 다시 시도해 주세요.'
        finally:
            busy = False
            if closed and not dialog.is_deleted:
                dialog.delete()
            if not dialog.is_deleted:
                generate.set_enabled(snapshot is not None and bool(snapshot.records))
                mask.enable()

    generate.on_click(create)
    try:
        snapshot = await run.io_bound(JournalPrintRepository(database).snapshot, request)
        if valid():
            message.text = counts_text(snapshot)
            generate.set_enabled(bool(snapshot.records))
    except Exception:
        if valid():
            message.text = '일지를 조회하지 못했습니다. 목록을 새로고침하고 다시 시도해 주세요.'
    if not valid():
        dialog.close()
        snapshot = None


def check_database(database):
    with database.session() as connection:
        connection.execute('SELECT 1').fetchone()


def counts_text(snapshot):
    return f'전체 {len(snapshot.records)}건 · ' + ' · '.join(f'{KINDS[k]} {v}건' for k, v in snapshot.counts.items() if v)


class PrintSelection:
    def __init__(self, database, kind, blocked=lambda: False):
        self.database, self.kind, self.blocked = database, kind, blocked
        self.scope = None
        self.ids = set()
        self.button = None

    def set_scope(self, scope):
        if scope != self.scope:
            self.ids.clear()
            self.scope = scope
            invalidate_prints(self.button.client if self.button is not None else None)
            if self.button is not None and not self.button.is_deleted:
                self.button.text = '선택 일지 PDF (0)'

    def toolbar(self):
        self.button = ui.button(f'선택 일지 PDF ({len(self.ids)})', icon='picture_as_pdf', on_click=self.download).props('outline')
        self.button.set_visibility(journal_pdf_visible(self.kind))

    async def download(self):
        if not self.ids:
            ui.notify('출력할 일지를 선택하세요.', type='warning')
            return
        await print_dialog(self.database, PrintRequest(refs=tuple((self.kind, key) for key in sorted(self.ids))),
                           self.button, self.blocked)

    def toggle(self, key, value):
        if value:
            self.ids.add(key)
        else:
            self.ids.discard(key)
        if self.button is not None and not self.button.is_deleted:
            self.button.text = f'선택 일지 PDF ({len(self.ids)})'

    def row(self, key):
        if not journal_pdf_visible(self.kind):
            return
        with ui.row().classes('items-center').on('click.stop', lambda: None).on('keydown.stop', lambda: None):
            ui.checkbox('선택', value=key in self.ids, on_change=lambda e: self.toggle(key, e.value)).props('dense')
            button = ui.button('PDF', icon='picture_as_pdf', on_click=lambda: print_dialog(
                self.database, PrintRequest(refs=((self.kind, key),)), button, self.blocked)).props('flat dense')


def list_print_tools(owner, database, kind, scope):
    if not hasattr(owner, 'pdf_selection'):
        owner.pdf_selection = PrintSelection(database, kind, lambda: owner.editor_open)
    owner.pdf_selection.set_scope(scope)
    if owner.pdf_selection.button is None or owner.pdf_selection.button.is_deleted:
        with owner.logs.parent_slot:
            owner.pdf_selection.toolbar()
            owner.pdf_selection.button.move(target_index=owner.logs.parent_slot.children.index(owner.logs))
    owner.pdf_selection.button.text = f'선택 일지 PDF ({len(owner.pdf_selection.ids)})'
    return owner.pdf_selection


def editor_print_button(database, kind, entry, blocked):
    if not journal_pdf_visible(kind):
        return None
    async def clicked():
        record = entry()
        if record is None:
            ui.notify('일지를 먼저 저장해 주세요.', type='warning')
            return
        await print_dialog(database, PrintRequest(refs=((kind, record.id),)), button, blocked)
    button = ui.button('PDF 출력', icon='picture_as_pdf', on_click=clicked).props('outline')
    button.set_enabled(entry() is not None)
    def refresh():
        if button.is_deleted:
            timer.deactivate()
        else:
            button.set_enabled(entry() is not None)
    timer = ui.timer(0.5, refresh)
    return button


def build_year_print(database):
    if not JOURNAL_PDF_VISIBLE:
        return
    with settings_card('학년도별 일지 PDF', 'picture_as_pdf',
                       '모든 종류의 일지를 학생·집단·교사별로 묶어 PDF 한 개로 출력합니다.', collapsible=True):
        year = ui.number('학년도', value=current_school_year(), min=1900, max=9998, step=1).props('outlined')
        ui.label('해당 연도 3월 1일~다음 해 2월 말일의 일지 날짜 기준입니다.')
        statuses = ui.select(STATUSES, value=['completed'], multiple=True, label='포함 상태').props('outlined').classes('w-full')
        ui.label('상태가 없는 심리검사·교육/행사는 항상 포함됩니다.').classes('text-sm text-slate-500')
        mask = ui.checkbox('이름 가리기', value=False)
        ui.label('학생 이름 대신 학생 ID를 표시합니다. 본문에 직접 작성한 이름은 자동으로 가려지지 않습니다.').classes('text-sm text-slate-500')
        async def prepare():
            try:
                if year.value is None or int(year.value) != year.value:
                    raise ValueError()
                request = PrintRequest(school_year=int(year.value), statuses=tuple(statuses.value), mask_names=mask.value)
                request.validate()
            except (ValueError, TypeError):
                ui.notify('학년도와 상태를 확인하세요.', type='warning')
                return
            button.disable()
            try:
                await print_dialog(database, request, button)
            finally:
                if not button.is_deleted:
                    button.enable()
        button = ui.button('건수 확인 및 PDF 출력', icon='picture_as_pdf', on_click=prepare)
