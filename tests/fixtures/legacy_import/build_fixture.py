"""Synthetic BIFF12 regression input; no real records or upstream code copied.

Run from the repository root: python tests/fixtures/legacy_import/build_fixture.py
This is a minimal reader fixture, not an Excel-generated interoperability sample.
"""
from io import BytesIO
from pathlib import Path
from struct import pack
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

PERSON = ['사례번호', '소속학교', '성명/집단명', '성별/인원', '학년', '반',
          '생년월일', '학생연락처', '보호자연락처', '비고']
LOG = ['접수', '일자', '교시', '시간(시)', '시간(분)', '사례번호', '소속학교',
       '성명/집단명', '성별/인원', '회기', '대상', '상담인원', '상담매체',
       '대분류', '중분류', '상담구분', '학년도', '상담일자', '상담제목', '상담내용',
       '기관유형', '상담분류', '상담자구분', '상담자성명']


def record(identifier, body=b''):
    size, length = len(body), bytearray()
    while size >= 128:
        length.append((size & 127) | 128)
        size >>= 7
    length.append(size)
    return identifier.to_bytes((identifier.bit_length() + 7) // 8 or 1, 'little') + length + body


def wide(value):
    data = value.encode('utf-16le')
    return pack('<I', len(data) // 2) + data


def make_fixture(*, duplicate_header=False, missing_header=False):
    strings = []

    def worksheet(rows, width):
        data = record(0x181) + record(0x194, pack('<IIII', 0, 9, 0, width - 1)) + record(0x191)
        for number, values in rows:
            data += record(0, pack('<I', number - 1))
            for column, value in enumerate(values):
                if value is None:
                    continue
                cell = pack('<II', column, 0)
                if isinstance(value, str):
                    strings.append(value)
                    data += record(7, cell + pack('<I', len(strings) - 1))
                else:
                    data += record(5, cell + pack('<d', value))
        return data + record(0x192) + record(0x182)

    # Shifted headings, whitespace, omitted middle cells, and skipped row numbers.
    headings = ['안내열'] + [' '+h+' ' for h in PERSON]
    if duplicate_header:
        headings.append('사례번호')
    if missing_header:
        headings[1] = '알 수 없는 열'
    people = worksheet([(1, ['합성 회귀검증 자료']), (3, headings),
                        (7, [None, 'TEST-001', None, '테스트학생', '남', 1, 2,
                             42005, None, None, '합성 데이터'])], len(headings))
    values = {'일자': 46200, '교시': '1', '시간(시)': 0, '시간(분)': 40,
              '사례번호': 'TEST-001', '성명/집단명': '테스트학생', '대상': '학생',
              '상담매체': '대면', '대분류': '상담', '중분류': '개인상담',
              '상담구분': '기타', '상담제목': '합성 기록', '상담내용': '첫 줄\n둘째 줄'}
    logs = worksheet([(2, LOG), (6, [values.get(h) for h in LOG]),
                      (10, [1 if h == '접수' else 2026 if h == '학년도' else None for h in LOG])], len(LOG))
    workbook = record(0x183) + record(0x18f)
    for number, name in enumerate(['인적사항등록', '상담대장'], 1):
        workbook += record(0x19c, pack('<II', 0, number) + wide(f'rId{number}') + wide(name))
    workbook += record(0x190)
    shared = record(0x19f, pack('<II', len(strings), len(strings)))
    shared += b''.join(record(0x13, b'\0' + wide(s)) for s in strings) + record(0x1a0)
    rels = b'<Relationships>' + b''.join(
        f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.bin"/>'.encode() for i in (1, 2)) + b'</Relationships>'
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, data in [('xl/workbook.bin', workbook), ('xl/_rels/workbook.bin.rels', rels),
                           ('xl/sharedStrings.bin', shared), ('xl/worksheets/sheet1.bin', people),
                           ('xl/worksheets/sheet2.bin', logs)]:
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
    return output.getvalue()


if __name__ == '__main__':
    Path(__file__).with_name('synthetic.xlsb').write_bytes(make_fixture())
