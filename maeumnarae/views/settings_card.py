"""설정 화면에서 사용하는 공통 카드 레이아웃."""

from collections.abc import Iterator
from contextlib import contextmanager

from nicegui import ui


@contextmanager
def settings_card(title: str, icon: str, description: str,
                  badge: str | None = None, *, collapsible: bool = False) -> Iterator[None]:
    if collapsible:
        with ui.card().classes(
            'w-full min-w-0 rounded-2xl border border-slate-200 shadow-sm bg-white p-0 overflow-hidden'
        ):
            with ui.expansion(title, icon=icon, caption=description).classes('w-full').props(
                'header-class="p-6 text-slate-800 font-semibold"'
            ):
                with ui.column().classes('w-full min-w-0 gap-5 px-6 pb-6'):
                    if badge:
                        ui.label(badge).classes('text-xs text-slate-500')
                    ui.separator()
                    yield
        return
    with ui.card().classes(
        'w-full min-w-0 rounded-2xl border border-slate-200 shadow-sm bg-white p-6 gap-5'
    ):
        with ui.row().classes('w-full items-start justify-between gap-3'):
            with ui.row().classes('items-center gap-3'):
                with ui.element('div').classes(
                    'flex items-center justify-center w-12 h-12 rounded-xl app-primary-soft text-primary'
                ):
                    ui.icon(icon, size='26px')
                ui.label(title).classes('text-xl font-bold text-slate-800')
            if badge:
                ui.label(badge).classes(
                    'rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-500'
                )
        ui.label(description).classes('text-sm text-slate-500')
        ui.separator()
        with ui.column().classes('w-full gap-5'):
            yield

