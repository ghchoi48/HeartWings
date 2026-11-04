import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from maeumnarae.widgets import weather


class DeviceRegionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.widget = weather.Weather(None, [])
        self.widget.loaded = True
        self.widget.body = SimpleNamespace(is_deleted=False)
        self.widget.location_label = SimpleNamespace(text='현재 기기 위치')
        self.widget.message = Mock()
        self.widget.render = Mock()

    async def test_device_region_updates_after_weather_renders(self):
        async def javascript(script, **kwargs):
            if script == weather.GEOLOCATION:
                return {'latitude': 37.57, 'longitude': 126.98}
            self.widget.render.assert_called_once()
            self.assertIn('"latitude": 37.57', script)
            return '서울특별시 · 종로구'

        with patch.object(weather.ui, 'run_javascript', side_effect=javascript), \
                patch.object(weather.run, 'io_bound', new=AsyncMock(return_value={'days': []})):
            await self.widget.reload()
        self.assertEqual(self.widget.location_label.text, '서울특별시 · 종로구')
        self.assertIsNone(self.widget.preferences['location'])

    async def test_manual_location_skips_reverse_geocoding(self):
        self.widget.preferences['location'] = {'name': '부산', 'latitude': 35.18, 'longitude': 129.07}
        with patch.object(weather.ui, 'run_javascript') as javascript, \
                patch.object(weather.run, 'io_bound', new=AsyncMock(return_value={} )):
            await self.widget.reload()
        javascript.assert_not_called()
        self.assertEqual(self.widget.location_label.text, '부산')

    async def test_failed_lookup_keeps_fallback(self):
        for result in (None, '', {}, TimeoutError()):
            with self.subTest(result=result):
                mock = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
                with patch.object(weather.ui, 'run_javascript', new=mock):
                    await self.widget.show_device_region(37.57, 126.98, 0)
                self.assertEqual(self.widget.location_label.text, '현재 기기 위치')

    async def test_stale_or_deleted_widget_does_not_update(self):
        for generation, deleted in ((1, False), (0, True)):
            self.widget.body.is_deleted = deleted
            with patch.object(weather.ui, 'run_javascript', new=AsyncMock(return_value='서울특별시')):
                await self.widget.show_device_region(37.57, 126.98, generation)
            self.assertEqual(self.widget.location_label.text, '현재 기기 위치')


if __name__ == '__main__':
    unittest.main()
