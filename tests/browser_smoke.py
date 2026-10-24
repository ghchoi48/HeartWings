"""실행 중인 로컬 앱을 Chrome 임시 프로필로 검사한다. 테스트 DB에만 사용한다.

실행: python tests/browser_smoke.py
별도 의존성: pip install playwright (설치된 Google Chrome 사용)
"""

from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    """실제 UI에서 학생 저장/수정과 DB 재열기를 확인한다."""
    output = Path(__file__).resolve().parents[1] / 'artifacts' / 'screenshots'
    output.mkdir(parents=True, exist_ok=True)
    password = 'runtime-test-only-20261015'
    name = '실행검증학생-' + uuid4().hex[:8]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_default_timeout(15000)
        try:
            response = page.goto('http://127.0.0.1:8765')
            assert response.status == 200
            expect(page.get_by_text('학생들의 이야기를 안전하게', exact=True)).to_be_visible()
            page.get_by_label('DB 비밀번호', exact=True).fill(password)
            confirmation = page.get_by_label('새 DB 비밀번호 확인', exact=True)
            if confirmation.is_visible():
                confirmation.fill(password)
                page.get_by_label('학교명', exact=True).fill('테스트학교')
                page.get_by_label('상담교사 이름', exact=True).fill('테스트교사')
                page.get_by_role('button', name='시작하기', exact=True).click()
            else:
                page.get_by_role('button', name='DB 열기', exact=True).click()
            expect(page.get_by_text('오늘도, 마음을 잇는 시간', exact=True)).to_be_visible()
            page.screenshot(path=str(output / 'home.png'), full_page=True)
            print('PASS: HTTP 200, DB 열기, 홈 화면', flush=True)

            page.get_by_role('button', name='학생 관리', exact=True).click()
            page.get_by_role('button', name='학생 추가', exact=True).click()
            dialog = page.get_by_role('dialog')
            dialog.get_by_label('이름', exact=True).fill(name)
            dialog.get_by_label('반', exact=True).fill('2')
            dialog.get_by_label('보호자 연락처', exact=True).fill('테스트 연락처')
            dialog.get_by_label('학생 메모', exact=True).fill('실행 검증용 가상 학생입니다.')
            dialog.get_by_role('button', name='저장', exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(page.get_by_role('button', name='학생 정보 수정', exact=True)).to_be_visible()
            print('PASS: 학생 추가 및 상세 프로필', flush=True)

            page.get_by_role('button', name='학생 정보 수정', exact=True).click()
            dialog.get_by_label('학생 메모', exact=True).fill('수정 후 다시 열기 검증 완료')
            dialog.get_by_role('button', name='저장', exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(page.get_by_text('수정 후 다시 열기 검증 완료', exact=True)).to_be_visible()
            page.get_by_label('이름 또는 학번', exact=True).fill(name)
            page.get_by_role('button', name='검색', exact=True).click()
            expect(page.get_by_role('cell', name=name, exact=True)).to_be_visible()
            page.get_by_role('button', name='홈', exact=True).click()
            expect(page.get_by_text('오늘도, 마음을 잇는 시간', exact=True)).to_be_visible()
            page.get_by_role('button', name='학생 관리', exact=True).click()
            expect(page.get_by_label('이름 또는 학번', exact=True)).to_have_value(name)
            print('PASS: 학생 수정, 검색, 사이드바 이동 및 검색 상태 유지', flush=True)

            page.reload()
            page.get_by_label('DB 비밀번호', exact=True).fill('wrong-password')
            page.get_by_role('button', name='DB 열기', exact=True).click()
            expect(page.get_by_text('DB를 열 수 없습니다. 비밀번호, 파일 상태와 접근 권한을 확인하세요.', exact=True)).to_be_visible()
            page.get_by_label('DB 비밀번호', exact=True).fill(password)
            page.get_by_role('button', name='DB 열기', exact=True).click()
            expect(page.get_by_text('오늘도, 마음을 잇는 시간', exact=True)).to_be_visible()
            page.get_by_role('button', name='학생 관리', exact=True).click()
            page.get_by_label('이름 또는 학번', exact=True).fill(name)
            page.get_by_role('button', name='검색', exact=True).click()
            row = page.get_by_role('row').filter(has=page.get_by_role('cell', name=name, exact=True))
            row.click()
            expect(page.get_by_text('수정 후 다시 열기 검증 완료', exact=True)).to_be_visible()
            page.screenshot(path=str(output / 'student.png'), full_page=True)
            assert not errors, errors
            print('PASS: 잘못된 키 거부, DB 재열기, 저장 내용 보존, JS 오류 없음', flush=True)

            page.get_by_role('button', name='상담 일지', exact=True).click()
            page.get_by_label('상담 대상 이름 또는 학번', exact=True).fill(name)
            page.get_by_role('button', name='학생 찾기', exact=True).click()
            page.get_by_role('row').filter(has=page.get_by_role('cell', name=name, exact=True)).get_by_role('checkbox').click()
            page.get_by_role('button', name='새 상담 일지', exact=True).click()
            dialog = page.get_by_role('dialog').filter(has=page.get_by_label('상담 제목', exact=True))
            dialog.get_by_role('button', name='일지 저장', exact=True).click()
            expect(dialog.get_by_text('제목·유형을 입력하고', exact=False)).to_be_visible()
            dialog.get_by_label('상담 제목', exact=True).fill('학교 적응 상담')
            dialog.get_by_label('상담 일시 (한국 시각)', exact=True).fill('2026-10-15T13:30')
            markdown = '## 상담 기록\n\n**학생의 이야기**\n\n- 학교 적응\n\n<script>window.previewUnsafe = true</script><svg onload="window.previewUnsafe=true"></svg>'
            dialog.get_by_label('상담 내용', exact=True).fill(markdown)
            expect(dialog.get_by_role('heading', name='상담 기록', exact=True)).to_be_visible()
            assert page.evaluate('window.previewUnsafe') is None
            assert dialog.locator('.nicegui-markdown [onload], .nicegui-markdown script').count() == 0
            dialog.get_by_label('후속 조치', exact=True).fill('다음 주 다시 만나기')
            page.screenshot(path=str(output / 'counseling-editor.png'), full_page=True)
            dialog.get_by_role('button', name='일지 저장', exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(page.get_by_text('학교 적응 상담', exact=True)).to_be_visible()
            expect(page.get_by_text('2026.10.15 13:30 · 완료 · 개인상담 · 50분', exact=True)).to_be_visible()
            page.get_by_role('button', name='일지 열기', exact=True).click()
            expect(dialog.get_by_label('상담 내용', exact=True)).to_have_value(markdown)
            dialog.get_by_label('상담 제목', exact=True).fill('버릴 제목')
            dialog.get_by_role('button', name='작성 닫기', exact=True).click()
            page.get_by_role('button', name='계속 작성', exact=True).click()
            expect(dialog.get_by_label('상담 제목', exact=True)).to_have_value('버릴 제목')
            dialog.get_by_role('button', name='작성 닫기', exact=True).click()
            page.get_by_role('button', name='변경 내용 버리기', exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(page.get_by_text('학교 적응 상담', exact=True)).to_be_visible()
            page.get_by_role('button', name='일지 열기', exact=True).click()
            dialog.get_by_label('상담 제목', exact=True).fill('학교 적응 상담 수정')
            dialog.get_by_role('button', name='일지 저장', exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(page.get_by_text('학교 적응 상담 수정', exact=True)).to_be_visible()
            page.get_by_role('button', name='학생 관리', exact=True).click()
            expect(page.get_by_text('2026.10.15 13:30 · 학교 적응 상담 수정', exact=True)).to_be_visible()
            print('PASS: 일지 입력 검증, 마크다운 미리보기/XSS 방어, 저장/수정, 취소 확인, 타임라인 갱신', flush=True)

            page.reload()
            page.get_by_label('DB 비밀번호', exact=True).fill(password)
            page.get_by_role('button', name='DB 열기', exact=True).click()
            page.get_by_role('button', name='상담 일지', exact=True).click()
            page.get_by_label('상담 대상 이름 또는 학번', exact=True).fill(name)
            page.get_by_role('button', name='학생 찾기', exact=True).click()
            page.get_by_role('row').filter(has=page.get_by_role('cell', name=name, exact=True)).get_by_role('checkbox').click()
            expect(page.get_by_text('학교 적응 상담 수정', exact=True)).to_be_visible()
            page.get_by_role('button', name='일지 열기', exact=True).click()
            expect(dialog.get_by_label('상담 내용', exact=True)).to_have_value(markdown)
            expect(dialog.get_by_label('후속 조치', exact=True)).to_have_value('다음 주 다시 만나기')
            assert not errors, errors
            print('PASS: DB 재열기 후 상담 원문·후속 조치 보존 및 JS 오류 없음', flush=True)
            dialog.get_by_role('button', name='작성 닫기', exact=True).click()
            expect(dialog).not_to_be_visible()
            page.get_by_role('button', name='캘린더', exact=True).click()
            page.get_by_label('기준 날짜', exact=True).fill('2026-10-15')
            page.get_by_role('button', name='날짜로 이동', exact=True).click()
            item_label = f'13:30 · {name} · 학교 적응 상담 수정'
            expect(page.get_by_text(item_label, exact=True)).to_be_visible()
            page.get_by_role('button', name='주간', exact=True).click()
            expect(page.get_by_text('2026.10.11 ~ 10.17', exact=True)).to_be_visible()
            page.get_by_role('button', name='월간', exact=True).click()
            expect(page.get_by_text('2026년 10월', exact=True)).to_be_visible()
            expect(page.get_by_text(item_label, exact=True)).to_be_visible()
            page.screenshot(path=str(output / 'calendar.png'), full_page=True)
            page.get_by_text(item_label, exact=True).locator('..').locator('..').get_by_role('button', name='일지 열기').click()
            expect(dialog.get_by_label('상담 제목', exact=True)).to_have_value('학교 적응 상담 수정')
            dialog.get_by_label('상담 일시 (한국 시각)', exact=True).fill('2026-10-15T13:45')
            dialog.get_by_role('button', name='일지 저장', exact=True).click()
            expect(dialog).not_to_be_visible()
            page.get_by_role('button', name='캘린더', exact=True).click()
            expect(page.get_by_text(f'13:45 · {name} · 학교 적응 상담 수정', exact=True)).to_be_visible()
            print('PASS: 월간/주간 달력, 일정 조회, 일지 연결 및 저장 후 일정 갱신', flush=True)

            page.get_by_role('button', name='통계', exact=True).click()
            page.get_by_label('통계 시작일', exact=True).fill('2026-10-01')
            page.get_by_label('통계 종료일', exact=True).fill('2026-10-31')
            page.get_by_role('button', name='통계 조회', exact=True).click()
            expect(page.get_by_role('button', name='CSV 내보내기', exact=True)).to_be_enabled()
            expect(page.get_by_text('유형별 완료 상담', exact=True)).to_be_visible()
            page.screenshot(path=str(output / 'statistics.png'), full_page=True)
            with page.expect_download() as download:
                page.get_by_role('button', name='CSV 내보내기', exact=True).click()
            csv_data = Path(download.value.path()).read_bytes()
            assert csv_data.startswith(b'\xef\xbb\xbf')
            assert '완료 상담(건)' in csv_data.decode('utf-8-sig')
            assert name not in csv_data.decode('utf-8-sig')
            with page.expect_download() as download:
                page.get_by_role('button', name='인쇄용 보고서', exact=True).click()
            html = Path(download.value.path()).read_text()
            assert '마음나래 상담 통계' in html and name not in html
            page.get_by_label('통계 시작일', exact=True).fill('2026-11-01')
            expect(page.get_by_role('button', name='CSV 내보내기', exact=True)).to_be_disabled()
            page.get_by_role('button', name='통계 조회', exact=True).click()
            expect(page.get_by_text('시작일과 종료일을 확인해 주세요.', exact=False)).to_be_visible()
            assert not errors, errors
            print('PASS: 기간 통계, 실제 CSV/HTML 다운로드, 개인정보 제외, 기간 변경·오류 방어', flush=True)
            page.reload()
            page.get_by_label('DB 비밀번호', exact=True).fill(password)
            page.get_by_role('button', name='DB 열기', exact=True).click()
            page.get_by_role('button', name='캘린더', exact=True).click()
            page.get_by_label('기준 날짜', exact=True).fill('2026-10-15')
            page.get_by_role('button', name='날짜로 이동', exact=True).click()
            page.get_by_text(f'13:45 · {name} · 학교 적응 상담 수정', exact=True).locator('..').locator('..').get_by_role('button', name='일지 열기').click()
            expect(dialog.get_by_label('상담 제목', exact=True)).to_have_value('학교 적응 상담 수정')
            assert not errors, errors
            print('PASS: 상담 화면을 방문하지 않고 캘린더에서 바로 일지 열기', flush=True)
        except BaseException:
            page.screenshot(path=str(output / 'failure.png'), full_page=True)
            raise
        finally:
            browser.close()


if __name__ == '__main__':
    main()
