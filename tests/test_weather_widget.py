import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from database import Database
from repositories.home_repo import HomeRepository
from services.weather import WeatherError, fetch_weather, search_regions, weather_status
from widgets.weather import Weather
from widgets import WIDGETS


def forecast():
    return {'temperature': 19, 'code': 0, 'is_day': True, 'time': '2026-10-22T12:00',
            'days': [{'date': date(2026, 10, 22) + timedelta(days=i), 'code': 61 if i else 0,
                      'low': 10 + i, 'high': 20 + i} for i in range(7)]}


async def inline(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def test_weather_storage_is_per_widget(tmp_path):
    db = Database('test-only', tmp_path / 'weather.db')
    db.initialize()
    repo = HomeRepository(db)
    assert repo.weather_preferences('a') == {'mode': 'daily', 'location': None}
    value = {'mode': 'weekly', 'location': {'name': '서울', 'latitude': 37.57, 'longitude': 126.98}}
    repo.save_weather_preferences('a', value)
    assert HomeRepository(db).weather_preferences('a') == value
    assert repo.weather_preferences('b')['location'] is None
    repo.save_layout([{'id': 'a', 'kind': 'weather', 'width': 8, 'height': 440}])
    assert repo.widget_sizes()['weather']['height'] == 440
    assert WIDGETS['weather'] is Weather
    with pytest.raises(ValueError):
        repo.save_weather_preferences('a', {'mode': 'weekly', 'location': {'name': 'bad', 'latitude': float('nan'), 'longitude': 0}})
    assert repo.weather_preferences('a') == value


def test_weather_response_and_search():
    payload = {'current': {'temperature_2m': 21, 'weather_code': 0, 'is_day': 0, 'time': '2026-10-22T20:00'},
               'daily': {'time': ['2026-10-22'], 'weather_code': [3], 'temperature_2m_min': [11], 'temperature_2m_max': [22]}}
    with patch('services.weather.request', return_value=payload) as request:
        result = fetch_weather(37, 127)
        assert result['temperature'] == 21
        assert result['days'][0]['low'] == 11
        assert not result['is_day']
        assert request.call_args.args[1]['timezone'] == 'auto'
    payload['daily']['temperature_2m_min'] = []
    with patch('services.weather.request', return_value=payload), pytest.raises(WeatherError):
        fetch_weather(37, 127)
    with patch('services.weather.request', return_value={'results': [{'name': '서울', 'country': '대한민국', 'latitude': 37, 'longitude': 127}]}):
        assert search_regions('서울')[0]['name'] == '서울 · 대한민국'
    with pytest.raises(WeatherError):
        search_regions('')
    assert weather_status(95)[0] == '뇌우'
    assert weather_status(71)[0] == '눈'


def test_location_failure_manual_region_and_modes():
    async def check():
        with Client(page('/weather-test')), patch('widgets.weather.ui.timer'), patch('widgets.weather.run.io_bound', side_effect=inline):
            home = Mock()
            home.weather_preferences.return_value = {'mode': 'daily', 'location': None}
            view = Weather(home, Mock(), 'a')
            view.build()
            with patch('widgets.weather.ui.run_javascript', new=AsyncMock(return_value=None)), patch('widgets.weather.fetch_weather') as fetch:
                await view.load()
                fetch.assert_not_called()
                assert any('위젯 설정 화면' in e.text for e in view.body.descendants() if isinstance(e, ui.label))
            location = {'name': '부산', 'latitude': 35.18, 'longitude': 129.07}
            await view.save_preferences({'mode': 'daily', 'location': location})
            with patch('widgets.weather.fetch_weather', return_value=forecast()) as fetch:
                await view.reload()
                fetch.assert_called_once_with(35.18, 129.07)
            assert view.location_label.text == '부산'
            assert any(e.text == '19°C' for e in view.body.descendants() if isinstance(e, ui.label))
            await view.change_mode(Mock(value='weekly'))
            assert len([e for e in view.body.descendants() if isinstance(e, ui.label) and e.text.startswith('최저')]) == 7
            home.save_weather_preferences.assert_called_with('a', {'mode': 'weekly', 'location': location})
    asyncio.run(check())


def test_device_location_and_stale_forecast():
    async def check():
        with Client(page('/weather-stale')), patch('widgets.weather.ui.timer'):
            view = Weather(Mock(), Mock())
            view.build()
            view.loaded = True
            started, release = asyncio.Event(), asyncio.Event()
            async def delayed(fn, *args):
                if args[0] == 37:
                    started.set()
                    await release.wait()
                result = forecast()
                result['temperature'] = args[0]
                return result
            with patch('widgets.weather.ui.run_javascript', new=AsyncMock(return_value={'latitude': 37, 'longitude': 127})), patch('widgets.weather.run.io_bound', side_effect=delayed):
                old = asyncio.create_task(view.reload())
                await started.wait()
                view.preferences['location'] = {'name': '다른 지역', 'latitude': 35, 'longitude': 129}
                await view.reload()
                release.set()
                await old
            assert view.data['temperature'] == 35
            assert view.location_label.text == '다른 지역'
    asyncio.run(check())


def test_inline_settings_search_and_save_without_forecast():
    import inspect

    async def click(button):
        listener = next(value for value in button._event_listeners.values() if value.type == 'click')
        callback = inspect.getclosurevars(listener.handler).nonlocals['callback']
        await callback()

    async def check():
        with Client(page('/weather-inline-settings')), patch('widgets.weather.ui.timer') as timer, \
                patch('widgets.weather.run.io_bound', side_effect=inline), \
                patch('widgets.weather.fetch_weather') as fetch, patch('widgets.weather.ui.notify'):
            home = Mock()
            home.weather_preferences.return_value = {'mode': 'weekly', 'location': None}
            view = Weather(home, Mock(), 'weather-a')
            host = ui.column()
            with host:
                view.build_settings()
            await timer.call_args.args[1]()
            elements = list(host.descendants())
            query = next(e for e in elements if isinstance(e, ui.input))
            query.value = '서울'
            location = {'name': '서울특별시', 'latitude': 37.57, 'longitude': 126.98}
            with patch('widgets.weather.search_regions', return_value=[location]):
                await click(next(e for e in elements if isinstance(e, ui.button) and e.text == '지역 검색'))
            await click(next(e for e in host.descendants() if isinstance(e, ui.button) and e.text == '서울특별시'))
            home.save_weather_preferences.assert_called_with('weather-a', {'mode': 'weekly', 'location': location})
            await click(next(e for e in elements if isinstance(e, ui.button) and e.text == '기기 위치 사용'))
            home.save_weather_preferences.assert_called_with('weather-a', {'mode': 'weekly', 'location': None})
            fetch.assert_not_called()
            assert not any(isinstance(e, ui.dialog) for e in host.descendants())
            with ui.column() as normal:
                Weather(home, Mock()).build()
            assert not any(isinstance(e, ui.button) and e.props.get('aria-label') == '날씨 지역 설정'
                           for e in normal.descendants())
    asyncio.run(check())
