"""한국 날짜 범위와 통계 보고서 직렬화. UI·DB에 의존하지 않는 순수 함수."""

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from html import escape

from maeumnarae.core.models import CounselingReport

KST = timezone(timedelta(hours=9))
STATUS_LABELS = {'scheduled': '예약', 'completed': '완료', 'cancelled': '취소'}


def date_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """양 끝 날짜를 포함하는 KST 구간을 [시작, 다음 날) datetime으로 변환한다."""
    if start > end:
        raise ValueError('종료일은 시작일보다 빠를 수 없습니다.')
    if end == date.max:
        raise ValueError('종료일은 9999-12-30 이전 날짜를 선택하세요.')
    return datetime.combine(start, time.min, KST), datetime.combine(end + timedelta(days=1), time.min, KST)


def report_rows(report: CounselingReport) -> list[list[str | int]]:
    """화면과 동일한 집계 스냅샷을 행으로 변환한다. 학생 식별정보·본문은 포함하지 않는다."""
    rows = [['구분', '항목', '값'], ['기간', '시작일', str(report.start)], ['기간', '종료일(포함)', str(report.end)],
            ['요약', '전체 일정(건)', report.total], ['요약', '완료 상담(건)', report.completed],
            ['요약', '완료 상담 학생(중복 제외)', report.students], ['요약', '완료 상담 시간(분)', report.minutes]]
    for group, buckets in [('상태별 전체', report.statuses), ('유형별 완료', report.categories),
                           ('월별 완료', report.months), ('현재 학년별 완료', report.grades)]:
        rows.extend([group, STATUS_LABELS.get(bucket.label, bucket.label) if group == '상태별 전체' else bucket.label,
                     bucket.count] for bucket in buckets)
    return rows


def report_csv(report: CounselingReport) -> bytes:
    """Excel에서 한글이 표시되는 UTF-8 BOM CSV. 수식으로 해석될 수 있는 텍스트를 방어한다."""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    for row in report_rows(report):
        writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@'))
                         else value for value in row])
    return stream.getvalue().encode('utf-8-sig')


def report_html(report: CounselingReport) -> bytes:
    """외부 리소스 없는 인쇄용 HTML. 브라우저 인쇄에서 PDF 저장도 가능하다."""
    body = ''.join('<tr>' + ''.join(f'<td>{escape(str(value))}</td>' for value in row) + '</tr>'
                   for row in report_rows(report)[1:])
    return f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>마음나래 상담 통계</title>
<style>body{{font:15px sans-serif;max-width:900px;margin:40px auto;color:#203b37}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #cbd5d1;padding:9px;text-align:left}}
th{{background:#edf6f3}}@media print{{body{{margin:0}}tr{{break-inside:avoid}}thead{{display:table-header-group}}}}</style>
<h1>마음나래 상담 통계</h1><p>{report.start} ~ {report.end} (종료일 포함 · 한국 표준시)</p>
<p>상담 시작일 기준. 유형·월·학년·학생 수·시간은 완료 상담만 집계합니다.
학년은 조회 시점의 학생 학년입니다. 학생 이름과 상담 내용은 포함하지 않습니다.</p>
<table><thead><tr><th>구분</th><th>항목</th><th>값</th></tr></thead><tbody>{body}</tbody></table></html>'''.encode('utf-8')
