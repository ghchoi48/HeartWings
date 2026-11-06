"""시간 입력은 오전/오후 12시간제로 표시하고 저장 시 24시간제로 변환한다."""

import re
from datetime import time

from nicegui import binding, ui


def parse_time(value: str) -> time:
    """화면의 A hh:mm 또는 기존 ISO 시각을 시간대 없는 시각으로 읽는다."""
    match = re.fullmatch(r'(오전|오후|AM|PM) (0[1-9]|1[0-2]):([0-5][0-9])', value)
    if match:
        period, hour, minute = match.groups()
        return time(int(hour) % 12 + (12 if period in ('오후', 'PM') else 0), int(minute))
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9](?:\.[0-9]{1,6})?)?', value):
        raise ValueError('시각은 오전/오후 hh:mm 형식으로 입력해 주세요.')
    result = time.fromisoformat(value)
    if result.tzinfo is not None:
        raise ValueError('시간대 없는 한국 시각을 입력해 주세요.')
    return result


def storage_time(value: str | None) -> str:
    """선택 입력의 빈 값은 유지하고 DB에는 HH:mm으로 저장한다."""
    return '' if not value else parse_time(value).isoformat(timespec='minutes')


def _period_text(value: str | None, *, korean: bool) -> str | None:
    """선택기의 영문 토큰과 입력창의 한글 표시를 양방향 변환한다."""
    periods = {'AM': '오전', 'PM': '오후'} if korean else {'오전': 'AM', '오후': 'PM'}
    if value:
        for source, target in periods.items():
            if value.startswith(source + ' '):
                return target + value[len(source):]
    return value


def time_input(label: str, *, value: str | None = '') -> ui.time_input:
    moment = parse_time(value) if value else None
    displayed = (f'{"오후" if moment.hour >= 12 else "오전"} '
                 f'{moment.hour % 12 or 12:02d}:{moment.minute:02d}') if moment else ''
    control = ui.time_input(label, value=displayed, placeholder='오전 09:00')
    control.picker.props('mask="A hh:mm"')
    control.picker.props['format24h'] = False
    # 기본 동일 값 바인딩을 교체하여 QTime의 A 토큰은 영문으로 유지한다.
    binding.remove([control.picker])
    control.picker.bind_value(control,
                             forward=lambda value: _period_text(value, korean=True),
                             backward=lambda value: _period_text(value, korean=False))
    control.picker.classes('korean-time-picker')
    # QTime의 AM/PM 헤더는 locale 옵션과 무관하게 영문으로 고정되어 있다.
    ui.add_css('''
        .korean-time-picker .q-time__header-ampm .q-time__link { font-size: 0; }
        .korean-time-picker .q-time__header-ampm .q-time__link::after { font-size: 14px; }
        .korean-time-picker .q-time__header-ampm .q-time__link:first-child::after { content: '오전'; }
        .korean-time-picker .q-time__header-ampm .q-time__link:last-child::after { content: '오후'; }
    ''')
    return control
