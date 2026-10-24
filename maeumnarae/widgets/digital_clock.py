"""한국 표준시 디지털 시계 위젯."""

from datetime import datetime, timedelta, timezone

from nicegui import ui


class DigitalClock:
    kind = 'clock'
    title = '디지털 시계'
    icon = 'schedule'

    def __init__(self, home, teachers, instance_id=None, on_change=None):
        pass

    def build(self) -> None:
        with ui.column().classes('w-full items-center justify-center flex-1 gap-3 py-8'):
            date = ui.label().classes('text-slate-500')
            clock = ui.label().classes('text-5xl font-bold text-teal-800 tabular-nums')
            ui.label('한국 표준시 · KST').classes('text-xs text-slate-400')

            def tick():
                now = datetime.now(timezone(timedelta(hours=9)))
                date.text = f'{now:%Y년 %m월 %d일} ({"월화수목금토일"[now.weekday()]})'
                clock.text = now.strftime('%H:%M:%S')

            tick()
            ui.timer(1, tick)
