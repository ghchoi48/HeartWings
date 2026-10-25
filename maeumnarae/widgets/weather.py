"""기기 위치 또는 직접 선택한 지역의 일간·주간 날씨."""
from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.services.weather import WeatherError, coordinates, fetch_weather, search_regions, weather_status

GEOLOCATION = '''return await new Promise(resolve => {
    if (!navigator.geolocation) { resolve(null); return; }
    navigator.geolocation.getCurrentPosition(
        p => resolve({latitude: p.coords.latitude, longitude: p.coords.longitude}),
        () => resolve(null), {enableHighAccuracy: false, timeout: 10000, maximumAge: 300000});
});'''


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

    def build(self):
        with ui.row().classes('w-full items-center flex-nowrap gap-1'):
            ui.icon('location_on').classes('text-primary')
            self.location_label = ui.label('현재 기기 위치').classes('font-semibold grow break-words')
            ui.button(icon='refresh', on_click=self.refresh).props('flat round aria-label="날씨 새로고침"')
        self.toggle = ui.toggle({'daily': '일간', 'weekly': '주간'}, value='daily',
                                on_change=self.change_mode).props('no-caps')
        self.body = ui.column().classes('w-full gap-3')
        ui.link('날씨: Open-Meteo · 지역: GeoNames', 'https://open-meteo.com/', new_tab=True).classes('text-xs text-slate-500')
        ui.timer(0, self.load, once=True)
        ui.timer(1800, self.reload)

    def message(self, text):
        if self.body.is_deleted:
            return
        self.body.clear()
        with self.body:
            ui.label(text).classes('text-sm text-slate-500')

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
        self.location_label.text = location['name'] if location else '현재 기기 위치'
        self.message('날씨를 불러오는 중입니다…' if location else '기기 위치를 확인하는 중입니다…')
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

    def temperatures(self, low, high):
        with ui.row().classes('gap-3 items-center'):
            ui.label(f'최저 {low:.0f}°').classes('text-blue-600 font-semibold')
            ui.label(f'최고 {high:.0f}°').classes('text-red-600 font-semibold')

    def render(self):
        self.body.clear()
        with self.body:
            if self.preferences['mode'] == 'daily':
                today = self.data['days'][0]
                description, icon = weather_status(self.data['code'], self.data['is_day'])
                with ui.row().classes('w-full items-center gap-4'):
                    ui.icon(icon, size='56px').classes('text-primary')
                    with ui.column().classes('gap-0'):
                        ui.label(f'{self.data["temperature"]:.0f}°C').classes('text-4xl font-bold')
                        ui.label(description).classes('text-lg')
                ui.label(f'오늘 · {today["date"]:%m월 %d일}').classes('text-sm text-slate-500')
                self.temperatures(today['low'], today['high'])
            else:
                for day in self.data['days']:
                    description, icon = weather_status(day['code'])
                    with ui.row().classes('w-full items-center justify-between gap-2 border-b pb-2'):
                        ui.label(f'{day["date"]:%m/%d} ({"월화수목금토일"[day["date"].weekday()]})').classes('text-sm')
                        with ui.row().classes('items-center gap-1'):
                            ui.icon(icon).classes('text-primary')
                            ui.label(description).classes('text-sm')
                        self.temperatures(day['low'], day['high'])
            ui.label(f'기준 {self.data["time"].replace("T", " ")} · 해당 지역 시각 · °C').classes('text-xs text-slate-500')

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
