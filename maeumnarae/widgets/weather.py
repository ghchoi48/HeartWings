"""기기 위치 또는 직접 선택한 지역의 일간·주간 날씨."""
import json

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.services.weather import WeatherError, coordinates, fetch_weather, search_regions, weather_status

GEOLOCATION = '''return await new Promise(resolve => {
    if (!navigator.geolocation) { resolve(null); return; }
    navigator.geolocation.getCurrentPosition(
        p => resolve({latitude: p.coords.latitude, longitude: p.coords.longitude}),
        () => resolve(null), {enableHighAccuracy: false, timeout: 10000, maximumAge: 300000});
});'''


# Client-only API, called with the device's current geolocation.
# https://www.bigdatacloud.com/docs/free-api/free-reverse-geocode-to-city-api
REGION_NAME = '''
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 5000);
try {
    const params = new URLSearchParams({...COORDINATES, localityLanguage: 'ko'});
    const response = await fetch('https://api.bigdatacloud.net/data/reverse-geocode-client?' + params,
                                 {signal: controller.signal, credentials: 'omit'});
    if (!response.ok) return null;
    const data = await response.json();
    const parts = [data.principalSubdivision, data.city, data.locality]
        .filter(value => typeof value === 'string' && value.trim()).map(value => value.trim());
    return [...new Set(parts)].join(' · ') || null;
} catch {
    return null;
} finally {
    clearTimeout(timer);
}
'''


# Keep Material 3 geometry while inheriting the existing application palette.
WEATHER_CSS = """
.weather-md3, .home-widget[data-kind="weather"] {
    --weather-surface: transparent; --weather-container: transparent;
    --weather-muted: #64748b;
    --weather-primary: var(--app-primary-accent, var(--q-primary));
    --weather-outline: #e5e7eb;
    --weather-low: #2563eb; --weather-high: #dc2626;
}
body.body--dark .weather-md3, body.body--dark .home-widget[data-kind="weather"] {
    --weather-muted: #b8c5d6;
}
.home-widget[data-kind="weather"].q-card {
    border-radius: 28px; box-shadow: none; border: 1px solid transparent;
}
.weather-md3 { width: 100%; gap: 12px; container-type: inline-size; }
.weather-location { flex: 1; min-width: 0; overflow-wrap: anywhere; font-weight: 500; }
.weather-md3 .weather-accent { color: var(--weather-primary); }
.weather-md3 .weather-muted { color: var(--weather-muted); }
.weather-refresh.q-btn { background: var(--weather-container); color: var(--weather-primary) !important;
    width: 32px; height: 32px; flex-shrink: 0; }
.weather-segments { flex-shrink: 0; border: 1px solid var(--weather-outline);
    border-radius: 24px; overflow: hidden; box-shadow: none; }
.weather-segments .q-btn { min-height: 32px; padding: 4px 10px; box-shadow: none; font-weight: 500; }
.weather-segments .q-btn + .q-btn { border-left: 1px solid var(--weather-outline); }
.weather-segments .q-btn[aria-pressed="true"] .q-btn__content::before {
    content: '✓'; margin-right: 8px;
}
.weather-md3 .q-btn:focus-visible, .weather-md3 a:focus-visible,
.weather-segments .q-btn:focus-visible, .weather-refresh.q-btn:focus-visible {
    outline: 2px solid var(--weather-primary); outline-offset: 3px;
}
.weather-hero { width: 100%; padding: 20px; border-radius: 24px;
    background: var(--weather-container); gap: 12px; }
.weather-temperature { font-size: 56px; font-weight: 400; line-height: 1.1; letter-spacing: -2px; }
.weather-unit { font-size: 24px; letter-spacing: 0; }
.weather-symbol { color: var(--weather-primary); margin-left: auto; }
.weather-temperatures { gap: 12px; flex-wrap: wrap; font-size: 13px; font-weight: 500;
    font-variant-numeric: tabular-nums; }
.weather-low { color: var(--weather-low); }
.weather-high { color: var(--weather-high); }
.weather-week { width: 100%; min-width: 0; display: flex; gap: 4px;
    overflow-x: auto; padding-bottom: 8px; }
.weather-week:focus-visible { outline: 2px solid var(--weather-primary); outline-offset: -2px; }
.weather-forecast { flex: 1 0 52px; min-width: 0; display: flex; flex-direction: column;
    align-items: center; gap: 8px; padding: 12px 8px; border-radius: 16px;
    text-align: center; background: var(--weather-surface); }
.weather-forecast:first-child { background: var(--weather-container); }
.weather-forecast .weather-temperatures { flex-direction: row; flex-wrap: nowrap;
    align-items: center; justify-content: center; gap: 4px; }
.weather-state { width: 100%; padding: 24px 16px; border-radius: 24px;
    background: var(--weather-container); gap: 12px; align-items: center; text-align: center; }
.weather-caption { font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
@container (max-width: 260px) {
    .weather-hero { padding: 16px; }
    .weather-temperature { font-size: 44px; }
    .weather-symbol { font-size: 44px !important; }
}
"""


class Weather:
    kind = 'weather'
    title = '날씨'
    icon = 'wb_cloudy'
    default_height = 440

    def __init__(self, home, teachers, instance_id=None, on_change=None):
        self.home = home
        self.instance_id = instance_id or 'weather'
        self.preferences = {'mode': 'daily', 'location': None}
        self.data = None
        self.generation = 0
        self.loaded = False
        self.saving = False

    def build_header_actions(self):
        self.toggle = ui.toggle({'daily': '일간', 'weekly': '주간'}, value=self.preferences['mode'],
                                on_change=self.change_mode).props(
            'no-caps unelevated dense aria-label="날씨 예보 기간"').classes('weather-segments')
        ui.button(icon='refresh', on_click=self.refresh).props(
            'flat round dense aria-label="날씨 새로고침"').classes('weather-refresh').tooltip('새로고침')

    def build(self):
        ui.add_css(WEATHER_CSS)
        with ui.column().classes('weather-md3'):
            with ui.row().classes('w-full items-center flex-nowrap gap-2'):
                ui.icon('location_on', size='20px').classes('weather-accent')
                self.location_label = ui.label('현재 기기 위치').classes('weather-location')
            self.body = ui.column().classes('w-full gap-2').props('aria-live=polite')
            with ui.row():
                ui.link('날씨: Open-Meteo · 지역: GeoNames', 'https://open-meteo.com/', new_tab=True).classes(
                'weather-caption weather-muted')
                ui.link('현재 위치 지역명: BigDataCloud', 'https://www.bigdatacloud.com/', new_tab=True).classes(
                'weather-caption weather-muted')
        ui.timer(0, self.load, once=True)
        ui.timer(1800, self.reload)

    def message(self, text, *, loading=False):
        if self.body.is_deleted:
            return
        self.body.clear()
        with self.body, ui.column().classes('weather-state'):
            if loading:
                ui.spinner(size='28px').classes('weather-accent')
            else:
                ui.icon('cloud_off', size='28px').classes('weather-accent')
            ui.label(text).classes('text-sm weather-muted')

    async def load(self):
        try:
            self.preferences = await run.io_bound(self.home.weather_preferences, self.instance_id)
        except DatabaseError as error:
            self.message(str(error))
            return
        if self.body.is_deleted:
            return
        self.toggle.set_value(self.preferences['mode'])
        self.loaded = True
        await self.reload()

    async def change_mode(self, event):
        if not self.loaded or event.value == self.preferences['mode']:
            return
        await self.save_preferences({**self.preferences, 'mode': event.value})
        if not self.body.is_deleted:
            self.toggle.set_value(self.preferences['mode'])
            if self.data:
                self.render()

    async def save_preferences(self, preferences):
        if self.saving:
            return False
        self.saving = True
        try:
            await run.io_bound(self.home.save_weather_preferences, self.instance_id, preferences)
            self.preferences = preferences
            return True
        except (DatabaseError, ValueError) as error:
            ui.notify(str(error), type='negative')
            return False
        finally:
            self.saving = False

    async def refresh(self):
        if self.loaded:
            await self.reload()
        else:
            await self.load()

    async def reload(self):
        if self.body.is_deleted or not self.loaded:
            return
        self.generation += 1
        generation = self.generation
        self.data = None
        location = self.preferences['location']
        device_location = location is None
        self.location_label.text = location['name'] if location else '현재 기기 위치'
        self.message('날씨를 불러오는 중입니다…' if location else '기기 위치를 확인하는 중입니다…', loading=True)
        try:
            if location is None:
                location = await ui.run_javascript(GEOLOCATION, timeout=12)
                if not location:
                    raise WeatherError('기기 위치를 확인할 수 없습니다. 위치 권한을 허용하거나 배치 편집 → 날씨 위젯 설정 화면에서 지역을 선택해 주세요.')
            lat, lon = coordinates(location['latitude'], location['longitude'])
            if generation != self.generation or self.body.is_deleted:
                return
            data = await run.io_bound(fetch_weather, lat, lon)
        except (WeatherError, TimeoutError, ValueError, KeyError, TypeError) as error:
            if generation == self.generation:
                self.message(str(error) if isinstance(error, WeatherError) else '위치를 확인하지 못했습니다. 배치 편집 → 날씨 위젯 설정 화면에서 지역을 선택해 주세요.')
            return
        if generation != self.generation or self.body.is_deleted:
            return
        self.data = data
        self.render()
        if device_location:
            await self.show_device_region(lat, lon, generation)

    async def show_device_region(self, latitude, longitude, generation):
        script = REGION_NAME.replace('COORDINATES', json.dumps(
            {'latitude': latitude, 'longitude': longitude}, allow_nan=False))
        try:
            name = await ui.run_javascript(script, timeout=7)
        except TimeoutError:
            return
        if (generation == self.generation and not self.body.is_deleted
                and isinstance(name, str) and name.strip()):
            self.location_label.text = name.strip()

    def temperatures(self, low, high, *, compact=False):
        with ui.row().classes('weather-temperatures items-center'):
            ui.label(f'{"" if compact else "최저 "}{low:.0f}°').classes('weather-low').props(
                f'aria-label="최저 {low:.0f}도"')
            ui.label(f'{"" if compact else "최고 "}{high:.0f}°').classes('weather-high').props(
                f'aria-label="최고 {high:.0f}도"')

    def render(self):
        self.body.clear()
        with self.body:
            if self.preferences['mode'] == 'daily':
                today = self.data['days'][0]
                description, icon = weather_status(self.data['code'], self.data['is_day'])
                with ui.column().classes('weather-hero'):
                    ui.label(f'오늘 · {today["date"]:%m월 %d일}').classes('text-sm weather-muted')
                    with ui.row().classes('w-full items-center flex-nowrap gap-3'):
                        with ui.column().classes('gap-1'):
                            with ui.row().classes('items-baseline flex-nowrap gap-1'):
                                ui.label(f'{self.data["temperature"]:.0f}°').classes('weather-temperature')
                                ui.label('C').classes('weather-unit weather-muted')
                            ui.label(description).classes('text-base font-medium')
                        ui.icon(icon, size='64px').classes('weather-symbol').props('aria-hidden=true')
                    self.temperatures(today['low'], today['high'])
            else:
                with ui.element('div').classes('weather-week').props(
                        'tabindex=0 role=region aria-label="주간 날씨 예보, 좌우로 스크롤"'):
                    for index, day in enumerate(self.data['days']):
                        description, icon = weather_status(day['code'])
                        with ui.element('div').classes('weather-forecast'):
                            weekday = "월화수목금토일"[day['date'].weekday()]
                            label = '오늘' if index == 0 else f'{weekday}요일'
                            ui.label(label).classes('text-sm font-medium')
                            ui.label(f'{day["date"]:%m/%d}').classes('text-xs weather-muted')
                            ui.icon(icon, size='28px').classes('weather-accent').props('aria-hidden=true')
                            ui.label(description).classes('text-xs weather-muted')
                            self.temperatures(day['low'], day['high'], compact=True)
            ui.label(f'기준 {self.data["time"].replace("T", " ")} · 해당 지역 시각 · °C').classes(
                'weather-caption weather-muted')

    async def open_settings(self):
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg p-6 gap-4'):
            self.build_settings()
            ui.button('닫기', on_click=lambda: dialog.submit(None)).props('flat').classes('self-end')
        try:
            await dialog
            if not self.body.is_deleted:
                await self.load()
        finally:
            if not dialog.is_deleted:
                dialog.delete()

    def build_settings(self):
        """설정 대화상자에 지역 설정을 표시한다."""
        with ui.column().classes('w-full gap-2') as settings:
            ui.label('날씨 지역 설정').classes('font-semibold')
            current = ui.label('설정을 불러오는 중입니다…').classes('text-sm text-slate-500')
            query = ui.input('지역명', placeholder='예: 서울, 부산, 제주').props('outlined maxlength=100').classes('w-full')
            results = ui.column().classes('w-full gap-1')
            search_generation = 0

            def show_location():
                location = self.preferences['location']
                current.text = f'현재 지역: {location["name"]}' if location else '현재 지역: 기기 위치 자동 사용'

            async def choose(location):
                if not self.loaded or settings.is_deleted:
                    return
                if await self.save_preferences({**self.preferences, 'location': location}):
                    if settings.is_deleted:
                        return
                    show_location()
                    results.clear()
                    ui.notify('날씨 지역을 저장했습니다.', type='positive')

            async def search():
                nonlocal search_generation
                if not self.loaded:
                    return
                search_generation += 1
                request = search_generation
                results.clear()
                with results:
                    ui.label('지역을 검색하는 중입니다…')
                try:
                    rows = await run.io_bound(search_regions, query.value or '')
                except WeatherError as error:
                    if request == search_generation and not results.is_deleted:
                        results.clear()
                        with results:
                            ui.label(str(error))
                    return
                if request != search_generation or results.is_deleted:
                    return
                results.clear()
                with results:
                    if not rows:
                        ui.label('검색 결과가 없습니다. 가까운 시·군 이름이나 영문 지역명을 입력해 보세요.')
                    for location in rows:
                        ui.button(location['name'], on_click=lambda location=location: choose(location)).props('flat align=left').classes('w-full')

            query.on('keydown.enter', search)
            with ui.row().classes('w-full gap-2'):
                search_button = ui.button('지역 검색', icon='search', on_click=search)
                device_button = ui.button('기기 위치 사용', icon='my_location', on_click=lambda: choose(None)).props('outline')
            search_button.disable()
            device_button.disable()

            async def initialize():
                try:
                    preferences = await run.io_bound(self.home.weather_preferences, self.instance_id)
                except DatabaseError as error:
                    if not settings.is_deleted:
                        current.text = str(error)
                    return
                if settings.is_deleted:
                    return
                self.preferences = preferences
                self.loaded = True
                show_location()
                search_button.enable()
                device_button.enable()

            ui.timer(0, initialize, once=True)
