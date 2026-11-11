"""일반, 화면, 시스템, DB, 내보내기, 프로그램 정보 탭으로 구성한 설정 화면."""

from collections.abc import Callable
from pathlib import Path
from subprocess import SubprocessError
import sys

from nicegui import run, ui

from maeumnarae.core.database import Database
from maeumnarae.core.desktop import open_folder
from maeumnarae.core.models import SchoolSettings
from maeumnarae.core.paths import PROJECT_ROOT
from maeumnarae.repositories.settings.school_settings_repo import SchoolSettingsRepository
from maeumnarae.views.settings.display_settings import DisplaySettings
from maeumnarae.views.shell.auto_lock import AutoLock
from maeumnarae.views.settings.password_settings_view import build_password_settings
from maeumnarae.views.settings.school_settings_view import build_school_settings
from maeumnarae.views.settings.about_view import build_about
from maeumnarae.views.settings.database_settings_view import build_database_settings
from maeumnarae.views.settings.export_settings_view import build_export_settings
from maeumnarae.views.shared.settings_card import settings_card
from maeumnarae.views.reports.journal_print_view import invalidate_prints



def build_settings(display: DisplaySettings | None = None,
                   school: SchoolSettingsRepository | None = None,
                   database: Database | None = None,
                   on_school_change: Callable[[SchoolSettings], None] | None = None,
                   on_roster_import=None,
                   auto_lock: AutoLock | None = None) -> None:
    """설정 종류별 탭을 만들고 기존 설정 컨트롤을 배치한다."""
    display = display or DisplaySettings()

    async def open_installation_folder():
        folder_button.disable()
        try:
            folder = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else PROJECT_ROOT
            await run.io_bound(open_folder, folder)
        except (OSError, SubprocessError):
            ui.notify('설치 폴더를 열지 못했습니다. 폴더 위치와 접근 권한을 확인해 주세요.', type='negative')
        finally:
            folder_button.enable()

    with ui.column().classes('w-full max-w-7xl mx-auto gap-6 p-4 md:p-8'):
        with ui.column().classes('gap-2'):
            ui.label('설정').classes('text-3xl font-bold text-slate-800')
            ui.label('화면부터 데이터 관리까지, 마음나래의 사용 환경을 설정하세요.').classes('text-slate-500')
        with ui.tabs().props('align=left outside-arrows mobile-arrows').classes('w-full') as tabs:
            ui.tab('general', label='일반', icon='tune')
            ui.tab('display', label='화면', icon='palette')
            ui.tab('system', label='시스템', icon='settings')
            ui.tab('db', label='DB', icon='storage')
            ui.tab('export', label='내보내기', icon='file_download')
            ui.tab('about', label='프로그램 정보', icon='info_outline')
        tabs.on_value_change(lambda: invalidate_prints(tabs.client))
        with ui.tab_panels(tabs, value='general').props('keep-alive').classes('w-full bg-transparent'):
            with ui.tab_panel('general').classes('p-0'):
                with settings_card('학교 정보 설정', 'school',
                                   '상담 업무에 사용할 학교 정보를 관리하세요.', '저장 후 적용'):
                    if school is not None:
                        build_school_settings(school, on_school_change)
            with ui.tab_panel('display').classes('p-0'):
                with settings_card('화면 설정', 'palette',
                                   '보기 편한 화면으로 맞춤 설정하세요.', '즉시 적용'):
                    display.build_controls()
            with ui.tab_panel('system').classes('p-0'):
                with settings_card('설치 폴더', 'folder_open',
                                   '마음나래 프로그램이 설치된 폴더를 엽니다.'):
                    folder_button = ui.button('설치 폴더 열기', icon='folder_open',
                                              on_click=open_installation_folder).props('outline')
                if auto_lock is not None:
                    with settings_card('자동 잠금', 'timer',
                                       '일정 시간 조작이 없으면 DB를 잠급니다.', '즉시 적용'):
                        auto_lock.build_controls()
                with settings_card('비밀번호 설정', 'lock_outline',
                                   '상담 기록을 보호하는 비밀번호를 관리하세요.', 'DB 비밀번호'):
                    if database is not None:
                        build_password_settings(database)
            with ui.tab_panel('db').classes('p-0'):
                with ui.column().classes('w-full gap-6'):
                    if database is not None:
                        build_database_settings(database, on_roster_import)
            with ui.tab_panel('export').classes('p-0'):
                with ui.column().classes('w-full gap-6'):
                    if database is not None:
                        build_export_settings(database)
            with ui.tab_panel('about').classes('p-0'):
                with settings_card('프로그램 정보', 'info_outline',
                                   '마음나래 프로그램을 소개합니다.'):
                    build_about()
