"""12시간제 입력의 자정·정오 변환 및 저장 형식 검증."""

import pytest
from nicegui import Client
from nicegui.page import page

from maeumnarae.views.time_inputs import parse_time, storage_time, time_input
from maeumnarae.views.counseling_view import counseling_form_input


@pytest.mark.parametrize(('stored', 'displayed'), [
    ('00:00', '오전 12:00'), ('09:05', '오전 09:05'),
    ('12:00', '오후 12:00'), ('15:30', '오후 03:30'),
    ('23:59', '오후 11:59'), ('', ''),
])
def test_time_input_round_trip(stored, displayed):
    with Client(page('/time-format-test')):
        control = time_input('시각', value=stored)
        assert control.value == displayed
        assert control.picker._props['mask'] == 'A hh:mm'
        assert control.picker._props['format24h'] is False
        assert not control.picker._props.get('with-seconds', False)
        assert storage_time(control.value) == stored


@pytest.mark.parametrize('value', ['AM 00:30', 'PM 13:30', 'PM 03:60', 'AM 09:00:15',
                                   '오전 00:30', '오후 13:30', '오후 03:60',
                                   '03:00+09:00', '24:00', ''])
def test_invalid_time(value):
    with pytest.raises(ValueError):
        parse_time(value)


@pytest.mark.parametrize(('clock', 'hour'), [('오전 12:30', 0), ('오후 12:30', 12), ('오후 03:30', 15)])
def test_counseling_form_keeps_korean_timezone(clock, hour):
    value = counseling_form_input(1, dict(starts_on='2026-10-22', starts_time=clock,
                                         title='상담', duration_minutes=50))
    assert value.starts_at.hour == hour
    assert value.starts_at.minute == 30
    assert value.starts_at.utcoffset().total_seconds() == 9 * 3600


def test_picker_and_manual_input_translate_both_ways():
    with Client(page('/korean-time-test')):
        control = time_input('시각', value='09:00')
        assert control.picker.value == 'AM 09:00'
        control.picker.value = 'PM 03:30'
        assert control.value == '오후 03:30'
        assert storage_time(control.value) == '15:30'
        control.value = '오전 12:15'
        assert control.picker.value == 'AM 12:15'
        assert storage_time(control.value) == '00:15'
        control.value = ''
        assert control.picker.value == ''
        assert storage_time(control.value) == ''
