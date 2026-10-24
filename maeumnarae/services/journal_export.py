"""상담관리 업로드 서식의 16개 열을 채우고 원본 XLSX 부속 요소를 보존한다."""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time
from io import BytesIO
import re
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

from maeumnarae.core.paths import RESOURCE_ROOT
from maeumnarae.services.reporting import KST, date_bounds
from maeumnarae.repositories.journal_export_repo import JournalExportRepository, JournalSnapshot

TEMPLATE = RESOURCE_ROOT / 'templates' / 'counseling_upload.xlsx'
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
KINDS = {'individual': '개인상담', 'group': '집단상담', 'special': '특별교육',
         'consultation': '자문', 'test': '심리검사', 'education': '교육/행사'}
AREAS = {
    '개인상담': ('학업', '진로', '성격', '성', '대인관계', '가정 및 가족관계', '일탈 및 비행',
              '학교폭력 가해', '학교폭력 피해', '자해 및 자살', '정신건강', '컴퓨터 및 스마트폰 과사용', '정보제공', '기타'),
    '학부모상담': ('학생관련상담', '교사관련상담', '학습', '기타'),
    '집단상담': ('학업', '진로', '학교폭력', '성격/대인관계', '기타'),
    '교원자문': ('학교학습', '사회성발달', '정서발달', '진로발달', '행동발달', '기타'),
}
METHODS = ('면담', '전화상담', '사이버상담')


@dataclass(frozen=True)
class ExportOptions:
    start: date | None = None
    end: date | None = None
    wee_class: str = 'Wee클래스'
    status: str = 'all'

    def validate(self):
        if (self.start is None) != (self.end is None):
            raise ValueError('시작일과 종료일을 함께 입력해 주세요.')
        if self.start is not None:
            date_bounds(self.start, self.end)
        if self.wee_class not in ('일반', 'Wee클래스'):
            raise ValueError('Wee클래스 구분을 확인해 주세요.')
        if self.status not in ('all', 'completed', 'completed_scheduled'):
            raise ValueError('내보낼 상태를 확인해 주세요.')


@dataclass(frozen=True)
class ExportResult:
    content: bytes
    count: int
    counts: dict[str, int]
    issues: tuple[str, ...]


def school_year(day: date) -> int:
    return day.year if day.month >= 3 else day.year - 1


def record_time(record: dict) -> datetime:
    if 'starts_at' in record:
        return datetime.fromisoformat(record['starts_at']).astimezone(KST)
    return datetime.combine(date.fromisoformat(record['day']),
                            time.fromisoformat(record['clock'] or '00:00'), KST)


def export_rows(snapshot: JournalSnapshot, options: ExportOptions):
    options.validate()
    rows, issues, counts = [], [], Counter()
    records = sorted(snapshot.records, key=lambda record: (record_time(record), record['kind'], record['id']))
    for record in records:
        day = record_time(record).date()
        if options.start is not None and not options.start <= day <= options.end:
            continue
        # 상태 필드가 없는 검사/교육 기록은 완료만 선택해도 포함한다.
        if options.status == 'completed' and record.get('status', 'completed') != 'completed':
            continue
        if options.status == 'completed_scheduled' and record.get('status', 'completed') not in ('completed', 'scheduled'):
            continue
        kind, year = record['kind'], school_year(day)
        problems = []
        area = record.get('area', '')
        target = record.get('target', '')
        major, middle = '상담', '개인상담'
        if kind == 'individual' and target in ('보호자(가족)', '보호자', '학부모'):
            middle = '학부모상담'
        elif kind == 'group':
            middle = '집단상담'
        elif kind == 'consultation':
            major, middle = '자문', '교원자문'
        elif kind == 'test':
            major, middle, area = '검사', '심리검사', '개인심리검사'
        elif kind == 'education':
            if record['category'] == '단체심리검사':
                major, middle, area = '검사', '심리검사', '집단심리검사'
            else:
                major, middle, area = '교육', '프로그램운영', '기타'
        if middle in AREAS and area not in AREAS[middle]:
            if kind in ('individual', 'consultation'):
                # 개인상담의 상담분야와 교원자문의 자문분야를 E열에 그대로 옮긴다.
                problems.append('상담/자문 분야 미입력 또는 서식에 없는 값(저장된 값 유지)')
            else:
                area = '기타'
                problems.append('상담 분야 미입력 또는 서식에 없는 값 → 기타')

        headcount = 1
        if kind == 'group':
            headcount = len(snapshot.members.get(record['group_id'], ())) or None
        elif kind == 'education':
            headcount = record.get('participant_count')
        if headcount is None:
            problems.append('상담인원 확인 필요(빈칸)')
        duration = record['duration_minutes']
        hours, minutes = divmod(duration, 60) if duration is not None else (None, None)
        if duration is None:
            problems.append('상담시간 확인 필요(빈칸)')
        method = (record.get('method') or '') if kind == 'individual' else '면담'
        if kind == 'individual' and method not in METHODS:
            problems.append('개인상담의 상담매체 미입력 또는 서식에 없는 값(저장된 값 유지)')
        rows.append(('전문상담', options.wee_class, major, middle, area, headcount, year,
                     day.strftime('%Y%m%d'), '', '', area, area, hours, minutes,
                     '전문상담교사', method))
        counts[KINDS[kind]] += 1
        if problems:
            issues.append(f'엑셀 {len(rows) + 1}행 · {KINDS[kind]} #{record["id"]} · {day}: ' + '; '.join(problems))
    return rows, tuple(issues), dict(counts)


def workbook_bytes(rows) -> bytes:
    """표준 라이브러리로 데이터 행만 추가하여 원본의 x14 유효성 검사도 유지한다.

    일반 XLSX 라이브러리의 재저장은 이 서식의 확장 유효성 검사를 제거하므로
    번들에 포함된 고정 서식의 입력 시트만 수정한다. 모든 문자열은 inlineStr이다.
    """
    if len(rows) > 1_048_575:
        raise ValueError('엑셀 최대 행 수를 초과했습니다. 기간을 나누어 내보내 주세요.')
    body = []
    for number, values in enumerate(rows, 2):
        cells = []
        if len(values) != 16:
            raise ValueError('업로드 서식은 16개 열이어야 합니다.')
        for column, value in zip('ABCDEFGHIJKLMNOP', values):
            address = f'{column}{number}'
            if value is None or value == '':
                cells.append(f'<c r="{address}" s="1"/>')
            elif isinstance(value, int):
                cells.append(f'<c r="{address}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{address}" s="1" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>')
        body.append(f'<row r="{number}" spans="1:16">{"".join(cells)}</row>')
    output = BytesIO()
    with ZipFile(TEMPLATE) as source, ZipFile(output, 'w', ZIP_DEFLATED) as destination:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == 'xl/worksheets/sheet1.xml':
                xml = content.decode('utf-8')
                xml = xml.replace('</sheetData>', ''.join(body) + '</sheetData>')
                xml = xml.replace('ref="A1:P1"', f'ref="A1:P{len(rows) + 1}"', 1)
                # 원본의 D/E 공용 검사는 E열에서도 대분류를 참조한다. E열은 중분류를 참조해야 한다.
                xml = xml.replace('<dataValidations count="2">', '<dataValidations count="3">')
                xml = xml.replace('sqref="D2:E3171"', 'sqref="D2:D3171"')
                xml = xml.replace('</dataValidations>', '<dataValidation type="list" allowBlank="1" showInputMessage="1" showErrorMessage="1" sqref="E2:E3171"><formula1>INDIRECT(D2)</formula1></dataValidation></dataValidations>', 1)
                xml = re.sub(r'(?P<column>[A-P])2:(?P=column)3171',
                             lambda match: f'{match[1]}2:{match[1]}{max(3171, len(rows) + 1)}', xml)
                content = xml.encode('utf-8')
            destination.writestr(item, content)
    return output.getvalue()


def export_journals(database, options: ExportOptions) -> ExportResult:
    rows, issues, counts = export_rows(JournalExportRepository(database).snapshot(), options)
    return ExportResult(workbook_bytes(rows), len(rows), counts, issues)
