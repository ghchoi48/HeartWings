"""학생·교사 XLSX 서식과 DB 쓰기 없는 행별 입력 검증."""

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from typing import Literal
from zipfile import BadZipFile, ZipFile
from xml.etree.ElementTree import ParseError
import re

from defusedxml.common import DefusedXmlException
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError

from maeumnarae.core.models import StudentInput, TeacherInput

ImportKind = Literal['students', 'teachers']
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
COLUMNS = {
    'students': [('name', '이름', True), ('grade', '학년', True), ('classroom', '반', True),
                 ('student_number', '번호', False), ('nickname', '별명', False),
                 ('birth_date', '생년월일', False), ('student_contact', '학생 연락처', False),
                 ('guardian_contact', '보호자 연락처', False), ('notes', '메모', False),
                 ('school_year', '학년도', False)],
    'teachers': [('name', '이름', True), ('contact', '연락처', False),
                 ('extension', '내선번호', False), ('responsibilities', '담당업무', False)],
}
TITLES = {'students': '학생', 'teachers': '교사'}


@dataclass(frozen=True)
class ImportRow:
    number: int
    value: StudentInput | TeacherInput


@dataclass(frozen=True)
class ImportBatch:
    kind: ImportKind
    rows: tuple[ImportRow, ...]
    errors: tuple[str, ...] = ()


def import_template(kind: ImportKind) -> bytes:
    """데이터 시트에는 실제 사람이나 예시 행을 넣지 않아 오등록을 방지한다."""
    columns = COLUMNS[kind]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = TITLES[kind]
    sheet.append([label + (' *' if required else '') for _, label, required in columns])
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = f'A1:{get_column_letter(len(columns))}{MAX_ROWS + 1}'
    sheet.row_dimensions[1].height = 30
    for index, (key, label, required) in enumerate(columns, 1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = 34 if key == 'notes' else 22
        header = sheet.cell(1, index)
        header.fill = PatternFill('solid', fgColor='176B60')
        header.font = Font(name='맑은 고딕', color='FFFFFF', bold=True)
        header.alignment = Alignment(vertical='center')
        header.comment = Comment('필수 입력 항목입니다.' if required else '선택 입력 항목입니다.', '마음나래')
        # 번호·연락처 앞자리 0을 보존한다. 날짜와 학년만 형식을 구분한다.
        number_format = '0' if key in ('grade', 'school_year') else 'yyyy-mm-dd' if key == 'birth_date' else '@'
        for row in range(2, MAX_ROWS + 2):
            sheet.cell(row, index).number_format = number_format
    if kind == 'students':
        validation = DataValidation(type='whole', operator='between', formula1=1, formula2=12)
        validation.errorTitle = '학년 확인'
        validation.error = '학년은 1~12 사이 정수로 입력하세요.'
        validation.showErrorMessage = True
        sheet.add_data_validation(validation)
        validation.add(f'B2:B{MAX_ROWS + 1}')
    guide = workbook.create_sheet('작성 안내')
    instructions = [
        f'{TITLES[kind]} 일괄 등록 서식',
        f'「{TITLES[kind]}」 시트의 2행부터 작성하세요. 별표(*)는 필수 항목입니다.',
        '제목 행은 유지하세요. 빈 행은 무시하며 한 파일당 최대 5,000명을 등록할 수 있습니다.',
        '번호·반·연락처·내선번호는 텍스트로 입력해 앞자리 0을 유지하세요.',
        '수식 대신 값을 입력하세요. 업로드 후 미리보기를 확인하고 등록 버튼을 누르세요.',
        '오류가 있으면 한 명도 등록되지 않습니다. 기존 자료를 수정하지 않고 새로 추가합니다.',
    ]
    if kind == 'students':
        instructions += ['학년은 1~12 사이 정수, 생년월일은 YYYY-MM-DD 또는 Excel 날짜로 입력하세요.',
                         '학년도는 4자리 연도입니다. 미입력 시 현재 학년도(3월 시작)를 사용합니다.',
                         '같은 학년도·학년·반 안에서 번호는 중복될 수 없습니다. 번호 미입력과 동명이인은 허용합니다.',
                         '기존 학생의 학적 추가는 학생 정보 수정에서 학년도를 변경해 저장하세요. 이 서식은 신규 학생 등록용입니다.']
    else:
        instructions += ['이름·연락처·내선번호·담당업무가 모두 같은 교사는 중복 등록할 수 없습니다.',
                         '동명이인은 나머지 정보로 구분하여 등록할 수 있습니다.']
    for instruction in instructions:
        guide.append([instruction])
    guide.column_dimensions['A'].width = 115
    guide['A1'].font = Font(name='맑은 고딕', size=16, bold=True, color='176B60')
    for row in guide:
        row[0].alignment = Alignment(wrap_text=True, vertical='center')
        guide.row_dimensions[row[0].row].height = 32
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _text(cell) -> str:
    value = cell.value
    if value is None:
        return ''
    if cell.data_type in ('f', 'e'):
        raise ValueError('수식이나 Excel 오류 대신 값을 입력하세요.')
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('문자 또는 숫자로 입력하세요.')
    if isinstance(value, (int, float)) and float(value).is_integer():
        text = str(int(value))
        if re.fullmatch(r'0+', cell.number_format or ''):
            return text.zfill(len(cell.number_format))
        return text
    return str(value).strip()


def parse_import(content: bytes, kind: ImportKind, *, target_year: int | None = None) -> ImportBatch:
    """손상/과대 파일, 필수 열, 수식, 모델 제약과 파일 내부 중복을 검사한다."""
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('10MB 이하의 XLSX 파일을 선택해 주세요.')
    workbook = None
    try:
        with ZipFile(BytesIO(content)) as archive:
            if len(archive.infolist()) > 256 or sum(entry.file_size for entry in archive.infolist()) > 80 * 1024 * 1024:
                raise ValueError('압축 해제 크기가 너무 큽니다. 파일을 나누어 등록해 주세요.')
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
        sheet_name = TITLES[kind]
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f'「{sheet_name}」 시트가 없습니다. 해당 서식 파일을 사용해 주세요.')
        sheet = workbook[sheet_name]
        if sheet.max_row and sheet.max_row > MAX_ROWS + 1:
            raise ValueError('한 파일당 5,000행까지 등록할 수 있습니다.')
        if sheet.max_column and sheet.max_column > len(COLUMNS[kind]):
            raise ValueError('서식보다 많은 열이 있습니다. 해당 서식 파일을 사용해 주세요.')
        sheet.reset_dimensions()
        columns = COLUMNS[kind]
        rows = sheet.iter_rows(max_row=MAX_ROWS + 2, max_col=len(columns) + 1)
        headers = [_text(cell).rstrip(' *') for cell in next(rows)]
        labels = {label: key for key, label, _ in columns}
        selected = [header for header in headers if header]
        if len(selected) != len(set(selected)) or any(header not in labels for header in selected):
            raise ValueError('제목 행에 중복되거나 알 수 없는 열이 있습니다. 서식 파일을 확인해 주세요.')
        required = [label for _, label, needed in columns if needed and label not in headers]
        if required:
            raise ValueError('필수 열이 없습니다: ' + ', '.join(required))
        records, errors, seen = [], [], set()
        for number, cells in enumerate(rows, 2):
            if all(cell.value is None or cell.value == '' for cell in cells):
                continue
            if number > MAX_ROWS + 1:
                raise ValueError('한 파일당 5,000행까지 등록할 수 있습니다.')
            try:
                if any(not header and cell.value not in (None, '') for header, cell in zip(headers, cells)):
                    raise ValueError('제목이 없는 열에 값이 있습니다.')
                data = {}
                for header, cell in zip(headers, cells):
                    if not header:
                        continue
                    key = labels[header]
                    if key == 'birth_date' and isinstance(cell.value, (date, datetime)):
                        data[key] = cell.value.date() if isinstance(cell.value, datetime) else cell.value
                    else:
                        data[key] = _text(cell)
                if kind == 'students':
                    data['student_number'] = data.get('student_number') or None
                    data['birth_date'] = data.get('birth_date') or None
                    if not data.get('school_year'):
                        data.pop('school_year', None)
                    if target_year is not None:
                        if data.get('school_year') and str(data['school_year']) != str(target_year):
                            raise ValueError('선택한 대상 학년도와 파일의 학년도가 다릅니다.')
                        data['school_year'] = target_year
                    value = StudentInput(**data)
                    identity = (value.school_year, value.grade, value.classroom, value.student_number) if value.student_number else None
                else:
                    value = TeacherInput(**data)
                    identity = (value.name, value.contact, value.extension, value.responsibilities)
                if identity is not None and identity in seen:
                    raise ValueError('파일 안에 중복된 번호가 있습니다.' if kind == 'students'
                                     else '파일 안에 모든 정보가 같은 교사가 있습니다.')
                if identity is not None:
                    seen.add(identity)
                records.append(ImportRow(number, value))
            except ValidationError as error:
                fields = ', '.join(dict.fromkeys(
                    next((label for key, label, _ in columns if item['loc'] and key == item['loc'][0]), '입력값')
                    for item in error.errors()))
                errors.append(f'{number}행: {fields}의 필수값, 형식 또는 길이를 확인하세요.')
            except (ValueError, TypeError) as error:
                errors.append(f'{number}행: {error}')
        if not records and not errors:
            raise ValueError('등록할 데이터가 없습니다. 2행부터 작성해 주세요.')
        return ImportBatch(kind, tuple(records), tuple(errors))
    except (ValueError, BadZipFile, KeyError, OSError, TypeError,
            ParseError, InvalidFileException, DefusedXmlException) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError('XLSX 파일을 읽지 못했습니다. 파일 형식과 손상 여부를 확인해 주세요.') from None
    finally:
        if workbook is not None:
            workbook.close()
