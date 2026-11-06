"""마음나래 페이지 구성과 데스크톱·브라우저 실행 설정."""

import argparse
import sys
from pathlib import Path

from nicegui import app, native, run, ui
from maeumnarae.services.ai.service import AIService
from maeumnarae.repositories.onboarding_repo import OnboardingRepository
from maeumnarae.repositories.school_settings_repo import SchoolSettingsRepository
from maeumnarae.views.onboarding_view import OnboardingView

from maeumnarae.core.database import Database, DatabaseError, default_database_path
from maeumnarae.repositories.counseling_repo import CounselingRepository
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.repositories.reporting_repo import ReportingRepository
from maeumnarae.views.app_layout import AppLayout
from maeumnarae.core.desktop import ICON_PATH, configure_logging, configure_native
from maeumnarae.views.display_settings import DEFAULT_PRIMARY, DisplaySettings
from maeumnarae.core.app_fonts import register_fonts
from maeumnarae.views.update_notification import StartupUpdateCheck


def register_page(path: Path) -> None:
    """페이지마다 비밀번호를 입력받는다. 전역으로 잠금 해제된 저장소를 공유하지 않는다."""
    register_fonts()

    cursor_dir = Path(__file__).resolve().parent.parent / 'resources' / 'cursors'
    app.add_static_files('/app-cursors', str(cursor_dir))


    ai_service = AIService(path.parent)
    app.on_shutdown(ai_service.close)
    update_check = StartupUpdateCheck()
    for name in ('icon.ico', 'icon-dark.ico', 'logo.png', 'logo-dark.png'):
        app.add_static_file(url_path=f'/app-assets/{name}', local_file=ICON_PATH.with_name(name))

    @ui.page('/')
    def index():
        first_run = not path.exists()
        ui.colors(primary=DEFAULT_PRIMARY, secondary='#64748b')
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

            /* 라이트 모드 */
            body:not(.body--dark) input,
            body:not(.body--dark) textarea,
            body:not(.body--dark) [contenteditable="true"] {
                cursor: url('/app-cursors/text-dark.cur'), text !important;
            }

            /* 다크 모드 */
            body.body--dark input,
            body.body--dark textarea,
            body.body--dark [contenteditable="true"] {
                cursor: url('/app-cursors/text-dark.cur'), text !important;
            }
        ''')
        drawer = ui.left_drawer(value=False, bordered=True).props('width=200').classes('bg-white p-4')
        drawer.set_visibility(False)
        with ui.header().classes('items-center justify-between px-6') as header:
            with ui.row().classes('items-center gap-3'):
                ui.image('/app-assets/logo.png').classes('app-logo w-9 h-9').props('no-spinner')
                school_heading = ui.label('마음나래 · Wee클래스').classes('text-lg font-bold')
        display = DisplaySettings(path.parent / 'display-settings.json')
        display.install()
        ui.context.client.content.classes('bg-slate-50')
        root = ui.column().classes('app-content w-full flex-1 min-h-0 flex-nowrap overflow-auto bg-slate-50')

        def start(database):
            root.clear()

            async def lock_database():
                await run.io_bound(database.lock)
                ui.navigate.to('/')

            AppLayout(StudentRepository(database), CounselingRepository(database),
                      ReportingRepository(database), on_lock=lock_database,
                      display=display, ai_service=ai_service,
                      on_school_change=lambda settings: school_heading.set_text(
                          settings.header_title,
                      )).build(root, drawer, header)
            drawer.set_visibility(True)
            drawer.show()

        with root:
            if first_run:
                OnboardingView(path, start).build()
            else:
                with ui.card().classes('w-full max-w-md mx-auto mt-16 p-8 rounded-2xl'):
                    ui.icon('lock_outline', size='40px').classes('text-primary')
                    ui.label('학생들의 이야기를 안전하게').classes('text-xl font-bold')
                    ui.label('상담 DB 비밀번호를 입력해 주세요.').classes('text-slate-500')
                    password = ui.input('DB 비밀번호', password=True, password_toggle_button=True).props('outlined').classes('w-full')
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
                        if not path.exists():
                            ui.navigate.to('/')
                            return
                        busy = True
                        button.disable()
                        message.text = 'DB를 확인하는 중입니다…'
                        try:
                            def open_database():
                                database = Database(secret, path)
                                database.initialize()
                                step = OnboardingRepository(database).get()
                                settings = SchoolSettingsRepository(database).get()
                                return database, step, settings
                            database, step, settings = await run.io_bound(open_database)
                        except (DatabaseError, ValueError) as error:
                            message.text = str(error)
                            password.value = ''
                            button.enable()
                            busy = False
                            return
                        password.value = ''
                        if step and step != 'complete':
                            root.clear()
                            with root:
                                OnboardingView(path, start, database, step, settings).build()
                        else:
                            start(database)

                    button = ui.button('DB 열기', icon='lock_open', on_click=unlock).classes('w-full')
                    password.on('keydown.enter', unlock)
        ui.timer(0.5, update_check.check, once=True)


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
        configure_native(args.db.parent / 'window-settings.json')
    port = args.port if args.port is not None else native.find_open_port() if args.native else 8080
    register_page(args.db)
    ui.run(title='마음나래', favicon=str(ICON_PATH), host='127.0.0.1', port=port,
           native=args.native, window_size=(1440, 1000) if args.native else None,
           reload=not args.native and not getattr(sys, 'frozen', False), language='ko-KR',
           show=not args.native and not args.no_open)

