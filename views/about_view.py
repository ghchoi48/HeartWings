"""프로그램 소개와 프로그램·서드파티 라이선스 표시."""

from nicegui import ui

from program_info import AUTHOR, GITHUB_URL, PROGRAM_NAME, program_license, third_party_notices


def license_text(text: str) -> None:
    # label을 사용해 라이선스의 줄바꿈과 원문을 유지하고 HTML로 해석하지 않는다.
    ui.label(text).classes(
        'w-full whitespace-pre-wrap break-words font-mono text-sm text-slate-700'
    )


def build_about() -> None:
    ui.label(PROGRAM_NAME).classes('text-2xl font-bold text-slate-800')
    ui.label('학교 Wee클래스와 전문상담교사를 위한 상담 관리 프로그램입니다.').classes('text-slate-600')
    ui.label('학생 정보와 상담 기록을 관리하고, 캘린더와 통계로 상담 업무를 확인할 수 있습니다.').classes('text-sm text-slate-500')
    ui.label(f'제작자: {AUTHOR}').classes('font-semibold text-slate-700')
    ui.link('GitHub 바로가기', GITHUB_URL, new_tab=True).classes('font-semibold')
    ui.separator()
    ui.label('프로그램 라이선스 · MIT License').classes('text-lg font-bold text-slate-800')
    license_text(program_license())
    ui.separator()
    ui.label('오픈소스 라이선스').classes('text-lg font-bold text-slate-800')
    notices = third_party_notices()
    for category, title in (('libraries', '라이브러리'), ('fonts', '폰트')):
        with ui.expansion(title, icon='description').classes('w-full'):
            for notice in notices[category]:
                with ui.expansion(notice['name']).classes('w-full'):
                    if notice.get('license'):
                        ui.label(notice['license']).classes('font-semibold text-slate-700')
                    if notice.get('source'):
                        ui.link('공식 사이트', notice['source'], new_tab=True)
                    if notice['text']:
                        license_text(notice['text'])
                    else:
                        ui.label('라이선스 고지를 준비 중입니다.').classes('text-sm text-slate-500')
