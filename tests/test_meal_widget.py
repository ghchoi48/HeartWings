"""나이스 요청·오류·구버전 학교 설정·급식 위젯 날짜 전환 검증."""

import asyncio
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest
from nicegui import Client, ui
from nicegui.page import page

from database import Database
from models import SchoolSettings
from repositories.school_settings_repo import SchoolSettingsRepository
from services.neis import NeisError, fetch_meals, find_schools, text_lines
from widgets.meal import Meal


def response(payload):
    stream = Mock()
    stream.__enter__ = Mock(return_value=stream)
    stream.__exit__ = Mock(return_value=False)
    stream.read.return_value = json.dumps(payload).encode()
    return stream


def test_meal_request_filters_date_school_and_meal_and_preserves_allergens():
    row = {'ATPT_OFCDC_SC_CODE': 'B10', 'SD_SCHUL_CODE': '7010057',
           'MLSV_YMD': '20261021', 'MMEAL_SC_CODE': '2', 'DDISH_NM': '밥<br/>국 (1.2.5)'}
    payload = {'mealServiceDietInfo': [{'head': [{'RESULT': {'CODE': 'INFO-000'}}]},
                                      {'row': [row, dict(row, MMEAL_SC_CODE='1')]}]}
    with patch('services.neis.urlopen', return_value=response(payload)) as request:
        assert fetch_meals('B10', '7010057', date(2026, 10, 21), '2', 'test-key') == [row]
    params = parse_qs(urlsplit(request.call_args.args[0]).query)
    assert params['KEY'] == ['test-key']
    assert params['MMEAL_SC_CODE'] == ['2']
    assert params['MLSV_YMD'] == ['20261021']
    assert request.call_args.kwargs['timeout'] == 10
    assert text_lines('밥<BR />국 (1.2.5)<br>과일 &amp; 우유') == ['밥', '국 (1.2.5)', '과일 & 우유']


def test_no_meal_api_error_and_network_failure_are_distinct():
    with patch('services.neis.urlopen', return_value=response({'RESULT': {'CODE': 'INFO-200'}})):
        assert fetch_meals('B10', '7010057', date(2026, 10, 21), '2') == []
    with patch('services.neis.urlopen', return_value=response({'RESULT': {'CODE': 'ERROR-290'}})):
        with pytest.raises(NeisError, match='인증키'):
            fetch_meals('B10', '7010057', date(2026, 10, 21), '2')
    with patch('services.neis.urlopen', side_effect=URLError('offline')):
        with pytest.raises(NeisError, match='연결'):
            find_schools('B10', '가락고등학교')
    with patch('services.neis.urlopen') as request:
        with pytest.raises(NeisError, match='학교 정보'):
            fetch_meals('', '', date(2026, 10, 21), '2')
        request.assert_not_called()


def test_school_neis_migration_and_persistence(tmp_path):
    db = Database('test-password', tmp_path / 'meal.db')
    db.initialize()
    with db.session(write=True) as connection:
        for column in ('neis_office_code', 'neis_school_code', 'neis_api_key'):
            connection.execute(f'ALTER TABLE school_settings DROP COLUMN {column}')
        connection.execute("UPDATE school_settings SET school_name='기존 학교'")
        connection.execute('PRAGMA user_version=25')
    db.initialize()
    repo = SchoolSettingsRepository(db)
    assert repo.get().school_name == '기존 학교'
    assert repo.get().neis_office_code == ''
    settings = SchoolSettings(school_name='가락고등학교', neis_office_code='B10',
                              neis_school_code='7010057', neis_api_key='test-key')
    repo.save(settings)
    db.initialize()
    assert SchoolSettingsRepository(Database('test-password', db.path)).get() == settings


class MealWidgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_today_lunch_date_and_meal_switching(self):
        with Client(page('/meal-widget-test')):
            home = Mock()
            widget = Meal(home, None)
            widget.school = Mock()
            widget.school.get.return_value = SchoolSettings(neis_office_code='B10', neis_school_code='7010057')
            host = ui.column()
            async def invoke(fn, *args, **kwargs):
                return fn(*args, **kwargs)
            with host, patch('widgets.meal.ui.timer'), patch('widgets.meal.run.io_bound', side_effect=invoke), \
                    patch('widgets.meal.fetch_meals', return_value=[]) as fetch:
                widget.build()
                original = widget.day
                assert widget.meal == '2'
                await widget.reload()
                fetch.assert_called_with('B10', '7010057', original, '2', '')
                await widget.move(1)
                assert (widget.day - original).days == 1
                await widget.select(SimpleNamespace(value='3'))
                fetch.assert_called_with('B10', '7010057', widget.day, '3', '')
                await widget.move(-1)
                assert widget.day == original
                widget.school.get.return_value = SchoolSettings(neis_office_code='J10', neis_school_code='1234567')
                await widget.reload()
                fetch.assert_called_with('J10', '1234567', original, '3', '')
            host.delete()

    async def test_slow_previous_response_cannot_replace_new_date(self):
        with Client(page('/meal-race-test')):
            widget = Meal(Mock(), None)
            widget.school = Mock()
            settings = SchoolSettings(neis_office_code='B10', neis_school_code='7010057')
            host = ui.column()
            started, release = asyncio.Event(), asyncio.Event()
            original = widget.day

            async def invoke(fn, *args, **kwargs):
                if fn == widget.school.get:
                    return settings
                if args[2] == original:
                    started.set()
                    await release.wait()
                    return [{'DDISH_NM': '이전 날짜 메뉴'}]
                return [{'DDISH_NM': '새 날짜 메뉴'}]

            with host, patch('widgets.meal.ui.timer'), patch('widgets.meal.run.io_bound', side_effect=invoke):
                widget.build()
                old = asyncio.create_task(widget.reload())
                await started.wait()
                await widget.move(1)
                release.set()
                await old
                texts = [element.text for element in widget.results.descendants() if isinstance(element, ui.label)]
                assert '새 날짜 메뉴' in texts
                assert '이전 날짜 메뉴' not in texts
            host.delete()
