"""DB와 독립적인 기기별 화면 설정 및 테마 적용."""

import json
import logging
from collections.abc import Callable
from pathlib import Path

from nicegui import ui

from maeumnarae.core.colors import (
    contrasting_text_color, normalize_color, readable_accent,
)
from maeumnarae.core.settings_store import SettingsStore
from maeumnarae.core.desktop import update_native_icon
from maeumnarae.core.app_fonts import FONTS, FONT_FAMILIES, font_face_css

MODES = {'auto': '자동 (기본값)', 'dark': '다크', 'light': '라이트'}

DEFAULT_PRIMARY = '#349E49'
PRIMARY_PRESETS = {
    'Wee Green': DEFAULT_PRIMARY,
    '청록': '#24756b', '파랑': '#3875f6', '보라': '#5f43ce',
    '장미': '#be185d',
}


class DisplaySettings:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.store = SettingsStore(path)
        self.values = {'mode': 'auto', 'size': 16, 'font': 'NotoSansKR-VariableFont_wght.ttf', 'primary': DEFAULT_PRIMARY}
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    if color := normalize_color(data.get('primary')):
                        self.values['primary'] = color
                    if data.get('mode') in MODES:
                        self.values['mode'] = data['mode']
                    if type(data.get('size')) is int and 12 <= data['size'] <= 22:
                        self.values['size'] = data['size']
                    if data.get('font') in FONTS:
                        self.values['font'] = data['font']
            except (OSError, ValueError, TypeError):
                logging.getLogger(__name__).warning('화면 설정을 읽을 수 없어 기본값을 사용합니다.')
        self.dark_mode = None
        self.primary_listeners: list[Callable[[str], None]] = []

    def install(self) -> None:
        ui.add_css(font_face_css())
        self.dark_mode = ui.dark_mode({'auto': None, 'dark': True, 'light': False}[self.values['mode']])
        ui.add_css('''
            :root { --app-primary-text: #ffffff; }
            body { --app-primary-accent: var(--app-primary-light); --app-calendar-timed-text: #000000; }
            body.body--dark { --app-primary-accent: var(--app-primary-dark); --app-calendar-timed-text: #ffffff; }
            .neis-school-name { color: #000000; }
            body.body--dark .neis-school-name { color: #ffffff; }
            .text-primary:not(.bg-primary) { color: var(--app-primary-accent) !important; }
            .app-primary-soft, .bg-app-primary-soft {
                background-color: color-mix(in srgb, var(--q-primary) 12%, white) !important;
            }
            body.body--dark .app-primary-soft, body.body--dark .bg-app-primary-soft {
                background-color: color-mix(in srgb, var(--q-primary) 22%, #1e293b) !important;
            }
            .app-primary-ring { --tw-ring-color: var(--q-primary) !important; }
            .app-primary-border { border-color: var(--q-primary) !important; }
            .bg-primary, .nicegui-header,
            .nicegui-header .q-btn { color: var(--app-primary-text) !important; }
            body { font-family: var(--app-font); font-size: 1rem; }
            .q-field, .q-btn, .q-table, .q-table th, .q-table tbody td { font-size: .875rem; }
            @layer overrides {
            body.body--dark { background: #0f172a; color: #e2e8f0; }
            body.body--dark .bg-white { background-color: #1e293b !important; }
            body.body--dark .bg-slate-50 { background-color: #0f172a !important; }
            body.body--dark .bg-slate-100 { background-color: #334155 !important; }
            body.body--dark .text-slate-800, body.body--dark .text-slate-700 { color: #e2e8f0 !important; }
            body.body--dark .text-slate-600, body.body--dark .text-slate-500 { color: #b8c5d6 !important; }

            body.body--dark .border-slate-200 { border-color: #475569 !important; }
            body.body--dark .q-editor__content { background: #1e293b; color: #e2e8f0; }
            }
        ''')
        ui.on('app_theme_changed', lambda e: update_native_icon(e.args is True))
        ui.run_javascript('''
            (() => {
                window.appThemeObserver?.disconnect();
                let previous;
                const update = () => {
                    const dark = document.body.classList.contains('body--dark');
                    const name = dark ? 'icon-dark' : 'icon';
                    document.querySelectorAll('link[rel~="icon"]').forEach(link => {
                        link.href = '/app-assets/' + name + '.ico';
                    });
                    document.querySelectorAll('.app-logo img').forEach(img => {
                        img.src = '/app-assets/' + (dark ? 'logo-dark.png' : 'logo.png');
                    });
                    if (previous !== dark) {
                        emitEvent('app_theme_changed', dark);
                        previous = dark;
                    }
                };
                window.appThemeObserver = new MutationObserver(update);
                window.appThemeObserver.observe(document.body, {attributes: true, attributeFilter: ['class']});
                update();
            })();
        ''')
        self.apply_typography()
        self.apply_primary()

    def apply_primary(self) -> None:
        color = self.values['primary']
        ui.colors(primary=color)
        variables = {
            '--app-primary-text': contrasting_text_color(color),
            '--app-primary-light': readable_accent(color, '#ffffff'),
            '--app-primary-dark': readable_accent(color, '#1e293b'),
        }
        ui.run_javascript(''.join(
            f'document.documentElement.style.setProperty({json.dumps(key)}, {json.dumps(value)});'
            for key, value in variables.items()
        ))
        for listener in self.primary_listeners:
            listener(color)

    def apply_typography(self) -> None:
        ui.run_javascript(
            f'document.documentElement.style.fontSize = {json.dumps(str(self.values["size"]) + "px")};'
            f'document.documentElement.style.setProperty("--app-font", '
            f'{json.dumps(FONT_FAMILIES[self.values["font"]])});'
        )

    def change(self, key: str, value) -> None:
        if key == 'primary' and (color := normalize_color(value)):
            self.values[key] = color
            self.apply_primary()
        elif key == 'mode' and value in MODES:
            self.values[key] = value
            if self.dark_mode is not None:
                self.dark_mode.value = {'auto': None, 'dark': True, 'light': False}[value]
        elif key == 'font' and value in FONTS:
            self.values[key] = value
            self.apply_typography()
        elif key == 'size' and isinstance(value, (int, float)) and 12 <= value <= 22:
            self.values[key] = int(value)
            self.apply_typography()
        else:
            return
        if self.path:
            try:
                self.store.update(lambda data: data.update({key: self.values[key]}))
            except (OSError, ValueError):
                ui.notify('화면에는 적용했지만 설정을 저장하지 못했습니다. 저장 폴더의 권한을 확인해 주세요.', type='negative')

    def build_controls(self) -> None:
        with ui.column().classes('w-full gap-2'):
            ui.label('화면 모드').classes('font-semibold text-slate-700')
            ui.select(MODES, value=self.values['mode'],
                      on_change=lambda e: self.change('mode', e.value)).props(
                'outlined aria-label="화면 모드"').classes('w-full')
            ui.label('자동 모드는 기기의 화면 모드를 따릅니다.').classes('text-sm text-slate-500')
        with ui.column().classes('w-full gap-2'):
            ui.label('폰트 설정').classes('font-semibold text-slate-700')
            ui.select(FONTS, value=self.values['font'],
                      on_change=lambda e: self.change('font', e.value)).props(
                'outlined aria-label="폰트 설정"').classes('w-full')
            ui.label('앱에 포함된 글꼴을 사용합니다.').classes('text-sm text-slate-500')
        with ui.column().classes('w-full gap-1'):
            size_label = ui.label(f'글자 크기 · {self.values["size"]}px').classes('font-semibold text-slate-700')

            def resize(e):
                self.change('size', e.value)
                size_label.text = f'글자 크기 · {self.values["size"]}px'

            ui.slider(min=12, max=22, step=1, value=self.values['size'], on_change=resize).props(
                'label label-always aria-label="글자 크기"'
            ).classes('w-full mt-4')
            ui.label('작게 12px · 기본 16px · 크게 22px').classes('text-sm text-slate-500')
        with ui.column().classes('w-full gap-2'):
            ui.label('기본 색상 (Primary)').classes('font-semibold text-slate-700')
            ui.label('버튼과 상단 바의 색상을 바꿉니다. 글씨 색상은 읽기 쉽게 자동 조절됩니다.').classes('text-sm text-slate-500')

            def pick_color(color):
                self.change('primary', color)
                color_label.set_text(self.values['primary'].upper())
                picker.set_color(self.values['primary'])

            with ui.row().classes('items-center'):
                with ui.button('색상 선택', icon='palette'):
                    picker = ui.color_picker(on_pick=lambda e: pick_color(e.color))
                    picker.set_color(self.values['primary'])
                    picker.q_color.props('format-model=hex')
                color_label = ui.label(self.values['primary'].upper()).classes('font-mono')
            with ui.row().classes('gap-2'):
                for name, color in PRIMARY_PRESETS.items():
                    ui.button(name, color=None, on_click=lambda color=color: pick_color(color)).style(
                        f'background-color: {color}; color: {contrasting_text_color(color)};'
                    ).props(f'aria-label="기본 색상 {name}"')
        ui.label('변경 사항은 즉시 적용되고 자동으로 저장됩니다.').classes('text-sm text-slate-500')
