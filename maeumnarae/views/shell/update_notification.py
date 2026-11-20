"""앱 실행 중 한 번만 업데이트를 확인하고 릴리스 변경사항을 표시한다."""

import sys
import webbrowser

from nicegui import run, ui

from maeumnarae.core.program_info import PROGRAM_VERSION
from maeumnarae.services.system.updates import Release, fetch_update


def show_update_dialog(release: Release) -> None:
    is_macos = sys.platform == 'darwin'

    async def download():
        if is_macos:
            await run.io_bound(webbrowser.open, release.url)
            return
        if release.download_url is None:
            ui.notify('이 릴리스에 다운로드할 Windows 설치 파일이 없습니다.', type='warning')
            return
        await run.io_bound(webbrowser.open, release.download_url)

    with ui.dialog() as dialog, ui.card().classes('w-[640px] max-w-full max-h-[85vh] flex-nowrap'):
        ui.label('새 버전 알림').classes('text-xl font-bold')
        ui.label(f'현재 버전 {PROGRAM_VERSION} → 새 버전 {release.version}').classes('text-sm text-slate-500')
        ui.separator()
        with ui.column().classes('w-full min-h-0 overflow-auto'):
            # 릴리스 본문을 HTML로 실행하지 않고 줄바꿈을 유지한다.
            ui.label(release.notes).classes('w-full whitespace-pre-wrap break-words')
        ui.separator()
        with ui.row().classes('w-full justify-end shrink-0'):
            ui.button('취소', on_click=dialog.close).props('flat')
            ui.button('다운로드 페이지 이동' if is_macos else '다운로드',
                      icon='open_in_new' if is_macos else 'download', on_click=download)
    dialog.open()


class StartupUpdateCheck:
    def __init__(self) -> None:
        self.checked = False

    async def check(self) -> None:
        if self.checked:
            return
        self.checked = True
        release = await run.io_bound(fetch_update)
        if release is not None:
            show_update_dialog(release)
