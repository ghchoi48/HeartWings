"""현재 시각까지의 미작성 일지 집계와 바로가기 목록."""
from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.home.home_repo import SCHEDULED_JOURNAL_LABELS
from maeumnarae.services.reports.reporting import KST

REFRESH_SECONDS = 60 * 60


class ScheduledJournals:
    kind = 'scheduled_journals'
    title = '미작성 일지'
    icon = 'pending_actions'

    def __init__(self, home, teachers, instance_id=None, on_change=None, *,
                 on_open=None, on_open_linked=None, is_active=None):
        self.home = home
        self.busy = False
        self.on_open = on_open
        self.on_open_linked = on_open_linked
        self.is_active = is_active or (lambda: True)

    def build_header_actions(self):
        self.refresh = ui.button(icon='refresh', on_click=self.reload).props(
            'flat round dense aria-label="미작성 일지 새로고침"').classes('shrink-0').tooltip('새로고침')

    def build(self):
        ui.label('현재 시각까지 · 상태가 예약인 일지 · 1시간마다 갱신').classes('text-xs text-slate-500')
        self.body = ui.column().classes('w-full gap-3')
        ui.timer(0, self.reload, once=True)
        ui.timer(REFRESH_SECONDS, self.reload)

    async def reload(self):
        if self.busy or self.body.is_deleted or not self.is_active() or self.home.database.is_locked:
            return
        self.busy = True
        self.refresh.disable()
        try:
            entries = await run.io_bound(self.home.scheduled_journals)
            if self.body.is_deleted or not self.is_active() or self.home.database.is_locked:
                return
            counts = dict.fromkeys(SCHEDULED_JOURNAL_LABELS.values(), 0)
            for entry in entries:
                counts[SCHEDULED_JOURNAL_LABELS[entry.source]] += 1
            self.body.clear()
            with self.body:
                with ui.row().classes('items-baseline gap-2'):
                    ui.label(f'{sum(counts.values()):,}').classes('text-5xl font-bold text-primary tabular-nums')
                    ui.label('건').classes('text-slate-500')
                with ui.grid(columns=2).classes('w-full gap-2'):
                    for label, count in counts.items():
                        with ui.row().classes('items-center justify-between rounded-lg bg-slate-50 p-3 gap-2'):
                            ui.label(label).classes('text-sm text-slate-600')
                            ui.label(f'{count:,}건').classes('font-semibold tabular-nums')
                if not any(counts.values()):
                    ui.label('미작성 일지가 없습니다.').classes('text-sm text-slate-500')
                else:
                    ui.separator()
                    ui.label('미작성 일지 목록 · 오래된 순').classes('text-sm font-semibold')
                    for entry in entries:
                        with ui.button(on_click=lambda entry=entry: self.open_journal(entry)).props(
                                'flat no-caps align=left').classes('w-full min-w-0'):
                            with ui.column().classes('w-full min-w-0 gap-1'):
                                ui.label(f'{entry.starts_at.astimezone(KST):%Y.%m.%d %H:%M} · '
                                         f'{SCHEDULED_JOURNAL_LABELS[entry.source]}').classes('text-xs text-slate-500')
                                ui.label(f'{entry.display_name} · {entry.title}').classes(
                                    'w-full truncate text-left').tooltip(f'{entry.display_name} · {entry.title}')
        except DatabaseError as error:
            if not self.body.is_deleted:
                self.body.clear()
                with self.body:
                    ui.label(str(error)).classes('text-sm text-red-700')
        finally:
            self.busy = False
            if not self.refresh.is_deleted:
                self.refresh.enable()

    async def open_journal(self, entry):
        if entry.source == 'counseling' and self.on_open:
            await self.on_open(entry.id)
        elif self.on_open_linked:
            await self.on_open_linked(entry)
