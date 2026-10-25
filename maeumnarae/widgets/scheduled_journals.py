"""오늘까지의 미작성 일지 건수와 일지 종류별 집계."""
from nicegui import run, ui

from maeumnarae.core.database import DatabaseError


class ScheduledJournals:
    kind = 'scheduled_journals'
    title = '미작성 일지'
    icon = 'pending_actions'

    def __init__(self, home, teachers, instance_id=None, on_change=None):
        self.home = home
        self.busy = False

    def build(self):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('오늘까지 · 상태가 예약인 일지').classes('text-xs text-slate-500')
            self.refresh = ui.button(icon='refresh', on_click=self.reload).props(
                'flat round aria-label="미작성 일지 새로고침"').tooltip('새로고침')
        self.body = ui.column().classes('w-full gap-3')
        ui.timer(0, self.reload, once=True)
        ui.timer(30, self.reload)

    async def reload(self):
        if self.busy or self.body.is_deleted:
            return
        self.busy = True
        self.refresh.disable()
        try:
            counts = await run.io_bound(self.home.scheduled_journal_counts)
            if self.body.is_deleted:
                return
            self.body.clear()
            with self.body:
                with ui.row().classes('items-baseline gap-2'):
                    ui.label(f'{sum(counts.values()):,}').classes('text-5xl font-bold text-teal-800 tabular-nums')
                    ui.label('건').classes('text-slate-500')
                with ui.grid(columns=2).classes('w-full gap-2'):
                    for label, count in counts.items():
                        with ui.row().classes('items-center justify-between rounded-lg bg-slate-50 p-3 gap-2'):
                            ui.label(label).classes('text-sm text-slate-600')
                            ui.label(f'{count:,}건').classes('font-semibold tabular-nums')
                if not any(counts.values()):
                    ui.label('미작성 일지가 없습니다.').classes('text-sm text-slate-500')
        except DatabaseError as error:
            if not self.body.is_deleted:
                self.body.clear()
                with self.body:
                    ui.label(str(error)).classes('text-sm text-red-700')
        finally:
            self.busy = False
            if not self.refresh.is_deleted:
                self.refresh.enable()
