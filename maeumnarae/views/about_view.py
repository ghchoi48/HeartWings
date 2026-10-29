"""프로그램 소개와 프로그램·서드파티 라이선스 표시."""

from nicegui import ui

from maeumnarae.core.program_info import AUTHOR, GITHUB_URL, PROGRAM_NAME, PROGRAM_VERSION, program_license, third_party_notices, third_party_source


def license_text(text: str) -> None:
    # label을 사용해 라이선스의 줄바꿈과 원문을 유지하고 HTML로 해석하지 않는다.
    ui.label(text).classes(
        'w-full whitespace-pre-wrap break-words font-mono text-sm text-slate-700'
    )


def build_about() -> None:
    ui.label(PROGRAM_NAME).classes('text-2xl font-bold text-slate-800')
    ui.label(f'현재 버전: {PROGRAM_VERSION}').classes('text-sm text-slate-500')
    ui.label('학교 Wee클래스와 전문상담교사를 위한 상담 관리 프로그램입니다.').classes('text-slate-600')
    ui.label('학생 정보와 상담 기록을 관리하고, 캘린더와 통계로 상담 업무를 확인할 수 있습니다.').classes('text-sm text-slate-500')
    ui.label(f'제작자: {AUTHOR}').classes('font-semibold text-slate-700')
    ui.link('GitHub 바로가기', GITHUB_URL, new_tab=True).classes('font-semibold')
    ui.separator()
    ui.label('프로그램 라이선스 · MIT License').classes('text-lg font-bold text-slate-800')
    ui.label(
        'MIT 라이선스는 상업적 이용을 포함해 누구나 자유롭게 사용·복사·수정·배포할 수 있는 오픈소스 라이선스입니다. '
        '복사본이나 소프트웨어의 주요 부분에는 저작권 표시와 라이선스 고지를 포함해야 하며, '
        '프로그램은 보증 없이 제공되고 제작자는 사용으로 인한 손해에 책임을 지지 않습니다.'
    ).classes('text-sm text-slate-600')
    license_text(program_license())
    ui.separator()
    ui.label('오픈소스 라이선스').classes('text-lg font-bold text-slate-800')
    ui.label('마음나래 자체 코드는 MIT 라이선스로 제공됩니다. pyxlsb에서 파생된 XLSB 읽기 구현은 LGPL-3.0-or-later이며, 포함된 라이브러리와 폰트에는 각각의 라이선스가 적용됩니다.').classes('text-sm text-slate-500')
    ui.label('항목을 펼치면 저작권 고지, 라이선스 전문과 제공된 소스 링크를 확인할 수 있습니다.').classes('text-sm text-slate-500')
    notices = third_party_notices()
    for category, title in (('libraries', '라이브러리'), ('fonts', '폰트')):
        with ui.expansion(title, icon='description', value=False).classes('w-full'):
            for notice in notices[category]:
                heading = notice['name']
                if notice.get('version'):
                    heading += f" {notice['version']}"
                if notice.get('license'):
                    heading += f" · {notice['license']}"
                with ui.expansion(heading).classes('w-full'):
                    if notice.get('license'):
                        ui.label(notice['license']).classes('font-semibold text-slate-700')
                    if notice.get('source'):
                        ui.link('공식 사이트', notice['source'], new_tab=True)
                    if notice.get('note'):
                        ui.label(notice['note']).classes('text-sm text-slate-500')
                    if notice.get('license_source'):
                        ui.link('라이선스 원문 출처', notice['license_source'], new_tab=True)
                    if notice.get('source_archive'):
                        ui.link('고지 버전의 원본 소스 다운로드', notice['source_archive'], new_tab=True)
                    if notice.get('source_file'):
                        source_file = notice['source_file']
                        ui.button('동봉된 원본 소스 저장', icon='download',
                                  on_click=lambda path=source_file: ui.download.content(
                                      third_party_source(path), path.rsplit('/', 1)[-1],
                                      media_type='application/gzip'))
                    if notice.get('modified_source_file'):
                        modified_source = notice['modified_source_file']
                        ui.button('사용된 라이브러리·파생 소스 저장', icon='download',
                                  on_click=lambda path=modified_source: ui.download.content(
                                      third_party_source(path), path.rsplit('/', 1)[-1],
                                      media_type='application/zip'))
                    if notice['text']:
                        with ui.column().classes('w-full max-h-96 overflow-auto'):
                            license_text(notice['text'])
                    else:
                        ui.label('라이선스 고지를 준비 중입니다.').classes('text-sm text-slate-500')
