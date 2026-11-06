"""공통 PDF 출력 대화상자와 개별·전체 일지 출력 UI."""
from dataclasses import replace
from datetime import date, datetime

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import current_school_year
from maeumnarae.repositories.reports.journal_export_repo import JournalExportRepository
from maeumnarae.repositories.reports.journal_print_repo import JournalPrintRepository
from maeumnarae.services.reports.journal_print_models import PrintRequest, KINDS
from maeumnarae.services.reports.reporting import KST
from maeumnarae.views.shared.settings_card import settings_card

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
            if request.school_year is not None:
                ui.label(f'{request.school_year}학년도 · {request.bounds[0]}부터 다음 해 2월 말일까지')
            elif request.start_date is not None:
                ui.label(f'{request.start_date} ~ {request.end_date} (시작일·종료일 포함)')
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
            from maeumnarae.services.reports.journal_pdf import build_pdf
            content = await run.io_bound(build_pdf, current, replace(request, mask_names=mask.value))
            # 생성 중 DB 잠금/교체도 확인한다.
            await run.io_bound(check_database, database)
            if not valid():
                return
            name = (f'마음나래_{request.school_year}학년도_전체일지.pdf' if request.school_year is not None else
                    f'마음나래_{request.start_date}_{request.end_date}_전체일지.pdf' if request.start_date is not None else
                    f'마음나래_{"전체일지" if request.all_records else "일지"}_{datetime.now(KST):%Y%m%d_%H%M%S}.pdf')
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


class JournalPrintButtons:
    def __init__(self, database, kind, blocked=lambda: False):
        self.database, self.kind, self.blocked = database, kind, blocked
        self.client = ui.context.client
        self.scope = None

    def set_scope(self, scope):
        if scope != self.scope:
            self.scope = scope
            invalidate_prints(self.client)

    def row(self, key):
        with ui.row().classes('items-center').on('click.stop', lambda: None).on('keydown.stop', lambda: None):
            button = ui.button('PDF', icon='picture_as_pdf', on_click=lambda: print_dialog(
                self.database, PrintRequest(refs=((self.kind, key),)), button, self.blocked)).props('flat dense')


def list_print_tools(owner, database, kind, scope):
    if not hasattr(owner, 'pdf_tools'):
        owner.pdf_tools = JournalPrintButtons(database, kind, lambda: owner.editor_open)
    owner.pdf_tools.set_scope(scope)
    return owner.pdf_tools


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


def build_all_print(database):
    with settings_card('모든 일지 PDF 내보내기', 'picture_as_pdf',
                       '선택한 기간의 개인상담·집단상담·특별교육·자문·심리검사·교육/행사 일지를 PDF 한 파일로 내보냅니다.', collapsible=True):
        with ui.row().classes('w-full items-end flex-nowrap overflow-x-auto'):
            period = ui.select({'year': '학년도', 'custom': '기간 직접 입력'},
                               value='year', label='내보낼 기간').props('outlined').classes('flex-1 min-w-[200px]')
            year = ui.select({}, label='학년도', with_input=True).props('outlined').classes('flex-1 min-w-[200px]')
            year.bind_visibility_from(period, 'value', backward=lambda value: value == 'year')
            start = ui.date_input('시작일', value=f'{current_school_year()}-03-01').props('outlined').classes('flex-1 min-w-[200px]')
            end = ui.date_input('종료일', value=datetime.now(KST).date().isoformat()).props('outlined').classes('flex-1 min-w-[200px]')
            start.bind_visibility_from(period, 'value', backward=lambda value: value == 'custom')
            end.bind_visibility_from(period, 'value', backward=lambda value: value == 'custom')
            status = ui.select({'completed': '완료만', 'completed_scheduled': '완료 및 예약'},
                               value='completed', label='내보낼 일지 상태').props('outlined').classes('flex-1 min-w-[200px]')
        message = ui.label().classes('text-sm text-slate-600')

        async def prepare():
            try:
                options = dict(statuses=('completed',) if status.value == 'completed' else ('completed', 'scheduled'))
                if period.value == 'year':
                    if year.value not in year.options:
                        raise ValueError()
                    request = PrintRequest(school_year=int(year.value), **options)
                elif period.value == 'custom':
                    request = PrintRequest(start_date=date.fromisoformat(start.value or ''),
                                           end_date=date.fromisoformat(end.value or ''), **options)
                else:
                    raise ValueError()
                request.validate()
            except (ValueError, TypeError, OverflowError):
                ui.notify('학년도 또는 시작일·종료일을 확인해 주세요. 시작일은 종료일보다 늦을 수 없습니다.', type='warning')
                return
            button.disable()
            try:
                await print_dialog(database, request, button)
            finally:
                if not button.is_deleted:
                    update_controls()

        button = ui.button('모든 일지 PDF 내보내기', icon='picture_as_pdf', on_click=prepare)

        def update_controls():
            year.set_enabled(period.value == 'year' and bool(year.options))
            start.set_enabled(period.value == 'custom')
            end.set_enabled(period.value == 'custom')
            button.set_enabled(period.value == 'custom' or year.value is not None)

        async def load_school_years():
            try:
                years = await run.io_bound(JournalExportRepository(database).school_years)
            except (DatabaseError, ValueError):
                message.text = '학년도 목록을 불러오지 못했습니다.'
                return
            current_year = current_school_year()
            selected = current_year if current_year in years else (years[0] if years else None)
            year.set_options({value: f'{value}학년도' for value in years}, value=selected)
            update_controls()
            if not years:
                message.text = '내보낼 일지 기록이 없습니다.'

        period.on_value_change(update_controls)
        year.on_value_change(update_controls)
        update_controls()
        ui.timer(0.01, load_school_years, once=True)
