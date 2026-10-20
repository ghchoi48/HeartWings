"""화면 설정 컨트롤과 학교 정보·비밀번호·DB 관리 안내 카드."""

from collections.abc import Callable

from nicegui import ui
from models import SchoolSettings
from views.display_settings import DisplaySettings
from repositories.school_settings_repo import SchoolSettingsRepository
from views.school_settings_view import build_school_settings
from views.password_settings_view import build_password_settings
from database import Database


def build_settings(display: DisplaySettings | None = None,
                   school: SchoolSettingsRepository | None = None,
                   database: Database | None = None,
                   on_school_change: Callable[[SchoolSettings], None] | None = None) -> None:
    """화면, 학교 정보, 비밀번호, DB 관리 항목을 반응형 카드로 표시한다."""
    display = display or DisplaySettings()
    cards = (
        (
            '화면 설정', 'palette', '보기 편한 화면으로 맞춤 설정하세요.',
            (),
        ),
        (
            '학교 정보 설정', 'school', '상담 업무에 사용할 학교 정보를 관리하세요.',
            (),
        ),
        (
            '비밀번호 설정', 'lock_outline', '상담 기록을 보호하는 비밀번호를 관리하세요.',
            (),
        ),
        (
            'DB 관리', 'storage', '상담 데이터의 보관 상태와 백업을 관리하세요.',
            (
                ('DB 정보', '현재 사용하는 DB의 위치와 용량을 확인합니다.'),
                ('DB 백업', '상담 데이터를 보관할 백업 파일을 만듭니다.'),
                ('DB 복원', '백업 파일에서 상담 데이터를 복원합니다.'),
            ),
        ),
    )
    with ui.column().classes('w-full max-w-7xl mx-auto gap-6 p-4 md:p-8'):
        with ui.column().classes('gap-2'):
            ui.label('설정').classes('text-3xl font-bold text-slate-800')
            ui.label('화면부터 데이터 관리까지, 마음나래의 사용 환경을 설정하세요.').classes('text-slate-500')
        with ui.element('div').classes('grid grid-cols-1 w-full md:grid-cols-2 gap-6'):
            for title, icon, description, items in cards:
                with ui.card().classes(
                    'w-full min-w-0 h-full rounded-2xl border border-slate-200 shadow-sm bg-white p-6 gap-5'
                ):
                    with ui.row().classes('w-full items-start justify-between gap-3'):
                        with ui.row().classes('items-center gap-3'):
                            with ui.element('div').classes(
                                'flex items-center justify-center w-12 h-12 rounded-xl bg-teal-50 text-teal-700'
                            ):
                                ui.icon(icon, size='26px')
                            ui.label(title).classes('text-xl font-bold text-slate-800')
                        ui.label('즉시 적용' if title == '화면 설정' else
                                 '저장 후 적용' if title == '학교 정보 설정' else
                                 'DB 비밀번호' if title == '비밀번호 설정' else '준비 중').classes(
                            'rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-500'
                        )
                    ui.label(description).classes('text-sm text-slate-500')
                    ui.separator()
                    with ui.column().classes('w-full gap-5'):
                        if title == '화면 설정':
                            display.build_controls()
                        elif title == '학교 정보 설정' and school is not None:
                            build_school_settings(school, on_school_change)
                        elif title == '비밀번호 설정' and database is not None:
                            build_password_settings(database)
                        for label, detail in items:
                            with ui.column().classes('gap-1'):
                                ui.label(label).classes('font-semibold text-slate-700')
                                ui.label(detail).classes('text-sm text-slate-500')
        with ui.row().classes('items-center gap-2 text-slate-500'):
            ui.icon('info_outline', size='18px')
            ui.label('DB 관리 기능은 준비 중입니다.').classes('text-sm')
