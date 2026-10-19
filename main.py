"""마음나래 데스크톱 진입점. frozen 자식 프로세스는 GUI import 전에 분기한다."""

from multiprocessing import freeze_support

if __name__ == '__main__':
    freeze_support()

import argparse
import sys
from pathlib import Path

from nicegui import app, native, run, ui

from database import Database, DatabaseError, default_database_path
from repositories.counseling_repo import CounselingRepository
from repositories.student_repo import StudentRepository
from repositories.reporting_repo import ReportingRepository
from views.app_layout import AppLayout
from desktop import ICON_PATH, configure_logging, configure_native


def register_page(path: Path) -> None:
    """페이지마다 비밀번호를 입력받는다. 전역으로 잠금 해제된 저장소를 공유하지 않는다."""

    @ui.page('/')
    def index():
        ui.colors(primary='#24756b', secondary='#64748b')
        ui.add_css('''
            html, body { overflow: hidden; }
            .q-page-container { height: 100dvh; overflow: hidden; }
            .q-page {
                height: 100%;
                min-height: 0 !important;
                display: flex;
                flex-direction: column;
            }
            .nicegui-content { flex: 1; min-height: 0; flex-wrap: nowrap; }
            .app-content > * { flex-shrink: 0; }
            .nicegui-drawer > .q-btn { flex-shrink: 0; }
        ''')
        drawer = ui.left_drawer(value=False, bordered=True).props('width=200').classes('bg-white p-4')
        drawer.set_visibility(False)
        with ui.header().classes('items-center justify-between px-6') as header:
            with ui.row().classes('items-center gap-3'):
                menu = ui.button(icon='menu', on_click=drawer.toggle).props('flat color=white aria-label=사이드바').tooltip('사이드바 열기/닫기')
                menu.set_visibility(False)
                ui.label('마음나래 · Wee클래스').classes('text-lg font-bold')
        root = ui.column().classes('app-content w-full flex-1 min-h-0 flex-nowrap overflow-auto bg-slate-50')
        with root:
            with ui.card().classes('w-full max-w-md mx-auto mt-16 p-8 rounded-2xl'):
                ui.icon('lock_outline', size='40px').classes('text-teal-700')
                ui.label('학생들의 이야기를 안전하게').classes('text-xl font-bold')
                ui.label('상담 DB 비밀번호를 입력해 주세요.').classes('text-slate-500')
                password = ui.input('DB 비밀번호', password=True, password_toggle_button=True).props('outlined').classes('w-full')
                confirmation = ui.input('새 DB 비밀번호 확인', password=True).props('outlined').classes('w-full')
                confirmation.set_visibility(not path.exists())
                message = ui.label().classes('text-red-700 text-sm')
                busy = False

                async def unlock():
                    nonlocal busy
                    if busy:
                        return
                    secret = password.value or ''
                    if not secret:
                        message.text = '비밀번호를 입력해 주세요.'
                        return
                    if not path.exists() and secret != confirmation.value:
                        confirmation.set_visibility(True)
                        message.text = '새 DB의 비밀번호를 다시 확인해 주세요.'
                        return
                    busy = True
                    button.disable()
                    message.text = 'DB를 확인하는 중입니다…'
                    try:
                        def open_database():
                            database = Database(secret, path)
                            database.initialize()
                            return database
                        database = await run.io_bound(open_database)
                    except (DatabaseError, ValueError) as error:
                        message.text = str(error)
                        password.value = ''
                        confirmation.value = ''
                        button.enable()
                        busy = False
                        return
                    password.value = ''
                    confirmation.value = ''
                    root.clear()

                    async def lock_database():
                        await run.io_bound(database.lock)
                        ui.navigate.to('/')

                    AppLayout(StudentRepository(database), CounselingRepository(database),
                              ReportingRepository(database), on_lock=lock_database).build(root, drawer, header)
                    menu.set_visibility(True)
                    drawer.set_visibility(True)
                    drawer.show()

                button = ui.button('DB 열기', icon='lock_open', on_click=unlock).classes('w-full')
                password.on('keydown.enter', unlock)


def main() -> None:
    """기본은 네이티브 창. --browser로 브라우저 모드를 선택한다."""
    parser = argparse.ArgumentParser(description='마음나래 상담 관리')
    parser.add_argument('--db', type=Path, default=default_database_path())
    parser.add_argument('--port', type=int, default=None, help='생략 시 네이티브는 빈 포트, 브라우저는 8080')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--native', dest='native', action='store_true', help='데스크톱 창으로 실행 (기본)')
    mode.add_argument('--browser', dest='native', action='store_false', help='브라우저에서 실행')
    parser.set_defaults(native=True)
    parser.add_argument('--no-open', action='store_true', help='브라우저 자동 열기 생략')
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('포트는 1~65535 범위여야 합니다.')
    configure_logging(args.db)
    if args.native:
        configure_native()
    port = args.port if args.port is not None else native.find_open_port() if args.native else 8080
    register_page(args.db)
    ui.run(title='마음나래', favicon=str(ICON_PATH), host='127.0.0.1', port=port,
           native=args.native, window_size=(1440, 1000) if args.native else None,
           reload=not getattr(sys, 'frozen', False), language='ko-KR',
           show=not args.native and not args.no_open)


if __name__ in {'__main__', '__mp_main__'}:
    main()
