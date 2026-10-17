"""홈 화면. 화면 이동은 주입받은 콜백을 사용하며 저장소에 의존하지 않는다."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from nicegui import ui


def build_home(on_students: Callable[[], None]) -> None:
    """시작 안내와 학생 관리 바로가기를 표시한다."""
    with ui.column().classes('w-full max-w-7xl mx-auto gap-6 p-4 md:p-8'):
        with ui.column().classes('gap-1'):
            ui.label('홈').classes('text-sm font-semibold text-teal-700')
            ui.label('오늘도, 마음을 잇는 시간').classes('text-3xl font-bold text-slate-800')
            ui.label('학생의 작은 변화와 소중한 이야기를 마음나래에 기록하세요.').classes('text-slate-500')
            date = ui.label().classes('text-sm text-slate-500')

            def update_date() -> None:
                date.text = datetime.now(timezone(timedelta(hours=9))).strftime('%Y년 %m월 %d일 · 한국 표준시')

            update_date()
            ui.timer(60, update_date)
        with ui.card().classes('w-full rounded-2xl shadow-sm p-6 md:p-8 bg-teal-50'):
            ui.icon('diversity_1', size='40px').classes('text-teal-700')
            ui.label('학생을 알아가는 첫걸음').classes('text-2xl font-bold text-slate-800')
            ui.label('학생을 등록하거나 검색하고, 프로필과 지난 상담 기록을 함께 살펴보세요.').classes('text-slate-600')
            ui.button('학생 관리로 이동', icon='arrow_forward', on_click=on_students).classes('mt-3')
        with ui.card().classes('w-full rounded-2xl shadow-sm p-6'):
            ui.label('이렇게 시작해 보세요').classes('text-xl font-bold text-slate-800')
            for icon, title, description in (
                ('person_add', '학생 등록', '이름, 학년, 반을 입력해 학생 프로필을 만듭니다.'),
                ('manage_search', '프로필 확인', '이름이나 학번으로 검색하고 연락처와 메모를 확인합니다.'),
                ('history', '상담 이력 살펴보기', '학생을 선택하고 상담 타임라인에서 이전 기록을 확인합니다.'),
            ):
                with ui.row().classes('items-start gap-4 py-3'):
                    ui.icon(icon, size='24px').classes('text-teal-700 mt-1')
                    with ui.column().classes('gap-1'):
                        ui.label(title).classes('font-semibold text-slate-700')
                        ui.label(description).classes('text-slate-500')
