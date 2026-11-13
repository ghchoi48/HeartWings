"""Calendar placeholders shown until the first local snapshot is ready."""
from nicegui import ui


def calendar_refresh_button(*, on_click, compact=False):
    ui.add_css('''
        @keyframes calendar-refresh-spin {
            to { transform: rotate(360deg); }
        }
        .calendar-refreshing .q-icon {
            animation: calendar-refresh-spin 1s linear infinite;
        }
    ''')
    return ui.button('' if compact else '새로고침', icon='refresh', on_click=on_click).props(
        'flat round dense aria-label="캘린더 새로고침"' if compact else 'flat aria-label="캘린더 새로고침"'
    ).tooltip('새로고침')


def set_calendar_refreshing(button, busy):
    if button is None or button.is_deleted:
        return
    button.classes(add='calendar-refreshing' if busy else '',
                   remove='' if busy else 'calendar-refreshing')
    button.props(f'aria-busy={str(busy).lower()}')
    button.set_enabled(not busy)


def show_calendar_skeleton(container, days, *, compact=False):
    container.clear()
    container.props('aria-busy=true')
    with container:
        with ui.column().classes('w-full gap-2').props('role=status aria-label="캘린더를 불러오는 중입니다"'):
            with ui.element('div').classes('w-full grid grid-cols-7 gap-1').props('aria-hidden=true'):
                for _ in range(7):
                    ui.skeleton('text').classes('w-6 mx-auto h-6')
                for _ in days:
                    if compact:
                        ui.skeleton('rect').classes('w-full h-10 rounded-lg')
                    else:
                        with ui.column().classes('min-w-0 min-h-28 border border-slate-200 p-2 gap-2'):
                            ui.skeleton('text').classes('w-10 h-6')
                            ui.skeleton('rect').classes('w-full h-5 rounded')
                            ui.skeleton('rect').classes('w-2/3 h-5 rounded')
            if compact:
                ui.skeleton('text').classes('w-24 h-6').props('aria-hidden=true')
                ui.skeleton('rect').classes('w-full h-9 rounded').props('aria-hidden=true')
