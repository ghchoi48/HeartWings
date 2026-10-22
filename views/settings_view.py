"""일반, 화면, 시스템, DB, 프로그램 정보 탭으로 구성한 설정 화면."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from nicegui import ui

from database import Database
from models import SchoolSettings
from repositories.school_settings_repo import SchoolSettingsRepository
from views.display_settings import DisplaySettings
from views.password_settings_view import build_password_settings
from views.school_settings_view import build_school_settings
from views.about_view import build_about
from views.database_settings_view import build_database_settings


@contextmanager
def settings_card(title: str, icon: str, description: str,
                  badge: str | None = None) -> Iterator[None]:
    with ui.card().classes(
        'w-full min-w-0 rounded-2xl border border-slate-200 shadow-sm bg-white p-6 gap-5'
    ):
        with ui.row().classes('w-full items-start justify-between gap-3'):
            with ui.row().classes('items-center gap-3'):
                with ui.element('div').classes(
                    'flex items-center justify-center w-12 h-12 rounded-xl bg-teal-50 text-teal-700'
                ):
                    ui.icon(icon, size='26px')
                ui.label(title).classes('text-xl font-bold text-slate-800')
            if badge:
                ui.label(badge).classes(
                    'rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-500'
                )
        ui.label(description).classes('text-sm text-slate-500')
        ui.separator()
        with ui.column().classes('w-full gap-5'):
            yield


def build_settings(display: DisplaySettings | None = None,
                   school: SchoolSettingsRepository | None = None,
                   database: Database | None = None,
                   on_school_change: Callable[[SchoolSettings], None] | None = None,
                   on_roster_import=None) -> None:
    """설정 종류별 탭을 만들고 기존 설정 컨트롤을 배치한다."""
    display = display or DisplaySettings()
    with ui.column().classes('w-full max-w-7xl mx-auto gap-6 p-4 md:p-8'):
        with ui.column().classes('gap-2'):
            ui.label('설정').classes('text-3xl font-bold text-slate-800')
            ui.label('화면부터 데이터 관리까지, 마음나래의 사용 환경을 설정하세요.').classes('text-slate-500')
        with ui.tabs().props('align=left outside-arrows mobile-arrows').classes('w-full') as tabs:
            ui.tab('general', label='일반', icon='tune')
            ui.tab('display', label='화면', icon='palette')
            ui.tab('system', label='시스템', icon='settings')
            ui.tab('db', label='DB', icon='storage')
            ui.tab('about', label='프로그램 정보', icon='info_outline')
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
                with settings_card('비밀번호 설정', 'lock_outline',
                                   '상담 기록을 보호하는 비밀번호를 관리하세요.', 'DB 비밀번호'):
                    if database is not None:
                        build_password_settings(database)
            with ui.tab_panel('db').classes('p-0'):
                with settings_card('DB 관리', 'storage',
                                   '상담 데이터의 보관 상태와 백업을 관리하세요.'):
                    if database is not None:
                        build_database_settings(database, on_roster_import)
            with ui.tab_panel('about').classes('p-0'):
                with settings_card('프로그램 정보', 'info_outline',
                                   '마음나래 프로그램을 소개합니다.'):
                    build_about()
