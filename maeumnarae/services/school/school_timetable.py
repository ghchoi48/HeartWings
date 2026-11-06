"""학교 시정표의 시간 형식·순서·중복 검증."""
import re


def normalize_timetable(rows):
    if not isinstance(rows, list) or len(rows) > 30:
        raise ValueError('시정표는 최대 30개 항목까지 등록할 수 있습니다.')
    result = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError('시정표 항목 형식을 확인해 주세요.')
        label, start, end = (row.get(key) for key in ('label', 'start', 'end'))
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 30:
            raise ValueError(f'{index}행: 교시/활동 이름을 1~30자로 입력해 주세요.')
        if any(not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value)
               for value in (start, end)):
            raise ValueError(f'{index}행: 시작·종료 시각을 입력해 주세요.')
        if start >= end:
            raise ValueError(f'{index}행: 종료 시각은 시작 시각보다 늦어야 합니다.')
        result.append(dict(label=label.strip(), start=start, end=end))
    result.sort(key=lambda row: row['start'])
    for previous, row in zip(result, result[1:]):
        if previous['end'] > row['start']:
            raise ValueError(f'“{previous["label"]}”과 “{row["label"]}”의 시간이 겹칩니다.')
    return result
