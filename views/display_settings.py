"""DB와 독립적인 기기별 화면 설정 및 테마 적용."""

import json
import logging
from pathlib import Path

from nicegui import ui

from settings_store import SettingsStore
from desktop import update_native_icon
from app_fonts import FONTS, FONT_FAMILIES, font_face_css

MODES = {'auto': '자동 (기본값)', 'dark': '다크', 'light': '라이트'}


class DisplaySettings:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.store = SettingsStore(path)
        self.values = {'mode': 'auto', 'size': 16, 'font': 'system'}
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    if data.get('mode') in MODES:
                        self.values['mode'] = data['mode']
                    if type(data.get('size')) is int and 12 <= data['size'] <= 22:
                        self.values['size'] = data['size']
                    if data.get('font') in FONTS:
                        self.values['font'] = data['font']
            except (OSError, ValueError, TypeError):
                logging.getLogger(__name__).warning('화면 설정을 읽을 수 없어 기본값을 사용합니다.')
        self.dark_mode = None

    def install(self) -> None:
        ui.add_css(font_face_css())
        self.dark_mode = ui.dark_mode({'auto': None, 'dark': True, 'light': False}[self.values['mode']])
        ui.add_css('''
            body { font-family: var(--app-font); font-size: 1rem; }
            .q-field, .q-btn, .q-table, .q-table th, .q-table tbody td { font-size: .875rem; }
            @layer overrides {
            body.body--dark { background: #0f172a; color: #e2e8f0; }
            body.body--dark .bg-white { background-color: #1e293b !important; }
            body.body--dark .bg-slate-50 { background-color: #0f172a !important; }
            body.body--dark .bg-slate-100 { background-color: #334155 !important; }
            body.body--dark .bg-teal-50 { background-color: #163c3b !important; }
            body.body--dark .text-slate-800, body.body--dark .text-slate-700 { color: #e2e8f0 !important; }
            body.body--dark .text-slate-600, body.body--dark .text-slate-500 { color: #b8c5d6 !important; }
            body.body--dark .text-teal-800, body.body--dark .text-teal-700 { color: #8fe0ce !important; }
            body.body--dark .text-primary { color: #8fe0ce !important; }
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
                        img.src = '/app-assets/' + (dark ? 'icon-dark.png' : 'icon.ico');
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

    def apply_typography(self) -> None:
        ui.run_javascript(
            f'document.documentElement.style.fontSize = {json.dumps(str(self.values["size"]) + "px")};'
            f'document.documentElement.style.setProperty("--app-font", '
            f'{json.dumps(FONT_FAMILIES[self.values["font"]])});'
        )

    def change(self, key: str, value) -> None:
        if key == 'mode' and value in MODES:
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
        ui.select(MODES, value=self.values['mode'], label='화면 모드',
                  on_change=lambda e: self.change('mode', e.value)).props('outlined').classes('w-full')
        ui.label('자동 모드는 기기의 화면 모드를 따릅니다.').classes('text-sm text-slate-500')
        with ui.column().classes('w-full gap-1'):
            size_label = ui.label(f'글자 크기 · {self.values["size"]}px').classes('font-semibold text-slate-700')

            def resize(e):
                self.change('size', e.value)
                size_label.text = f'글자 크기 · {self.values["size"]}px'

            ui.slider(min=12, max=22, step=1, value=self.values['size'], on_change=resize).props(
                'label label-always aria-label="글자 크기"'
            ).classes('w-full mt-4')
            ui.label('작게 12px · 기본 16px · 크게 22px').classes('text-sm text-slate-500')
        ui.select(FONTS, value=self.values['font'], label='폰트 설정',
                  on_change=lambda e: self.change('font', e.value)).props('outlined').classes('w-full')
        ui.label('앱에 포함된 글꼴을 사용합니다. 선택한 글꼴은 아래에서 미리 볼 수 있습니다.').classes('text-sm text-slate-500')
        with ui.element('div').classes('w-full rounded-xl bg-slate-50 p-4'):
            ui.label('마음나래에서 학생의 이야기를 기록하세요.').classes('text-base')
        ui.label('변경 사항은 즉시 적용되고 자동으로 저장됩니다.').classes('text-sm text-slate-500')
