"""프로그램 정보에서 공개 릴리스 변경 내역을 확인하는 모달."""

from nicegui import run, ui

from maeumnarae.core.program_info import GITHUB_URL, PROGRAM_VERSION
from maeumnarae.services.system.updates import fetch_release_history, version_numbers


async def show_update_history() -> None:
    page = 1
    busy = False
    has_more = False

    async def load(target: int):
        nonlocal page, busy, has_more
        if busy or dialog.is_deleted:
            return
        busy = True
        previous.disable()
        following.disable()
        retry.disable()
        body.clear()
        with body:
            ui.spinner(size='24px')
            ui.label('업데이트 내역을 불러오는 중입니다…')
        try:
            releases, more = await run.io_bound(fetch_release_history, target)
            if dialog.is_deleted:
                return
            page, has_more = target, more
            body.clear()
            with body:
                if not releases:
                    ui.label('이 페이지에 등록된 정식 업데이트 내역이 없습니다.').classes('text-sm text-slate-500')
                for release in releases:
                    current = version_numbers(release.version) == version_numbers(PROGRAM_VERSION)
                    heading = f'{release.version}' + (' · 현재 설치 버전' if current else '')
                    with ui.expansion(heading, icon='history', value=False).classes('w-full'):
                        ui.label(release.notes).classes('w-full whitespace-pre-wrap break-words text-sm')
                        ui.link('GitHub에서 보기', release.url, new_tab=True)
            page_label.text = f'{page}페이지'
        except (OSError, ValueError):
            if not dialog.is_deleted:
                body.clear()
                with body:
                    ui.label('업데이트 내역을 불러오지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.').classes('text-sm text-red-700')
        finally:
            busy = False
            if not dialog.is_deleted:
                previous.set_enabled(page > 1)
                following.set_enabled(has_more)
                retry.enable()

    with ui.dialog() as dialog, ui.card().classes('w-[720px] max-w-full max-h-[85vh] flex-nowrap'):
        ui.label('업데이트 내역').classes('text-xl font-bold')
        ui.label(f'현재 버전: {PROGRAM_VERSION} · GitHub에 게시된 정식 릴리스').classes('text-sm text-slate-500')
        body = ui.column().classes('w-full min-h-0 overflow-auto gap-3')
        ui.separator()
        with ui.row().classes('w-full items-center gap-2 shrink-0'):
            previous = ui.button('이전', on_click=lambda: load(page - 1)).props('flat')
            page_label = ui.label('1페이지').classes('text-sm')
            following = ui.button('다음', on_click=lambda: load(page + 1)).props('flat')
            retry = ui.button(icon='refresh', on_click=lambda: load(page)).props(
                'flat round aria-label="업데이트 내역 새로고침"').tooltip('다시 불러오기')
            ui.space()
            ui.link('전체 내역', f'{GITHUB_URL}/releases', new_tab=True)
            ui.button('닫기', on_click=dialog.close).props('flat')
    dialog.on('hide', dialog.delete)
    dialog.open()
    await load(1)
