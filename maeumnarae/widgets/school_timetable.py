"""직접 편집하는 학교 시정표와 한국 시각 기준 현재 교시 표시."""
from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.views.time_inputs import storage_time, time_input

KST = timezone(timedelta(hours=9))


def active_period(rows, now):
    clock = now.astimezone(KST).strftime('%H:%M')
    return next((row for row in rows if row['start'] <= clock < row['end']), None)


class SchoolTimetable:
    kind = 'school_timetable'
    title = '학교 시정표'
    icon = 'view_timeline'

    def __init__(self, home, teachers, instance_id=None, on_change=None):
        self.home = home
        self.rows = []
        self.busy = False
        self.editing = False

    def build(self):
        self.body = ui.column().classes('w-full gap-1')
        ui.timer(0, self.reload, once=True)
        ui.timer(15, self.reload)

    async def open_settings(self):
        await self.edit()

    async def reload(self):
        if self.busy or self.body.is_deleted:
            return
        self.busy = True
        try:
            rows = await run.io_bound(self.home.school_timetable)
            if not self.body.is_deleted:
                self.rows = rows
                self.render()
        except (DatabaseError, ValueError) as error:
            if not self.body.is_deleted:
                self.body.clear()
                with self.body:
                    ui.label(str(error)).classes('text-sm text-red-700')
                    ui.button('다시 불러오기', on_click=self.reload).props('flat dense')
        finally:
            self.busy = False

    def render(self):
        self.body.clear()
        current = active_period(self.rows, datetime.now(KST))
        with self.body:
            if not self.rows:
                ui.label('위젯 편집을 눌러 시정표를 등록하세요.').classes('text-sm text-slate-500')
                return
            ui.label(f'현재 {current["label"]} · {current["end"]} 종료' if current else
                     '현재 진행 중인 교시/활동이 없습니다.').classes('text-xs leading-5 font-semibold text-red-700')
            for row in self.rows:
                with ui.row().classes('w-full items-center justify-between flex-nowrap rounded-md px-2 py-1 gap-2 ' +
                                      ('bg-red-50 border border-red-300' if row == current else 'bg-slate-50')):
                    ui.label(row['label']).classes('min-w-0 text-sm leading-5 font-semibold break-all')
                    ui.label(f'{row["start"]}–{row["end"]}').classes('shrink-0 text-xs leading-5 tabular-nums whitespace-nowrap text-slate-600')

    async def edit(self):
        if self.editing or self.body.is_deleted:
            return
        self.editing = True
        dialog = None
        try:
            rows = await run.io_bound(self.home.school_timetable)
            if self.body.is_deleted:
                return
            fields = []
            saving = False
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-3xl p-6 gap-4'):
                    ui.label('학교 시정표 편집').classes('text-xl font-bold')
                    ui.label('교시·점심시간 등 최대 30개 항목을 등록할 수 있습니다. 시작 시각순으로 저장하며 모든 시정표 위젯에 적용됩니다.').classes('text-sm text-slate-500')
                    rows_box = ui.column().classes('w-full max-h-[55vh] overflow-auto gap-2')
                    message = ui.label().classes('text-sm text-red-700')

                    def add_row(row=None):
                        if saving or len(fields) >= 30:
                            return
                        row = row or dict(label='', start='', end='')
                        with rows_box, ui.row().classes('w-full items-center flex-nowrap gap-2') as container:
                            label = ui.input('교시/활동', value=row['label']).props('outlined maxlength=30').classes('flex-1 min-w-0')
                            start = time_input('시작 시각', value=row['start']).props('outlined').classes('flex-1 min-w-0')
                            end = time_input('종료 시각', value=row['end']).props('outlined').classes('flex-1 min-w-0')
                            item = (label, start, end)

                            def remove():
                                if not saving:
                                    fields.remove(item)
                                    container.delete()

                            ui.button(icon='delete_outline', on_click=remove).props('flat round color=negative aria-label="시정표 항목 삭제"')
                        fields.append(item)

                    for row in rows:
                        add_row(row)
                    if not rows:
                        add_row()
                    add = ui.button('항목 추가', icon='add', on_click=lambda: add_row()).props('outline')

                    async def save():
                        nonlocal saving
                        if saving:
                            return
                        saving = True
                        controls = [add, save_button, cancel, *rows_box.descendants()]
                        for control in controls:
                            if hasattr(control, 'disable'):
                                control.disable()
                        try:
                            values = [dict(label=label.value, start=storage_time(start.value), end=storage_time(end.value))
                                      for label, start, end in fields]
                            await run.io_bound(self.home.save_school_timetable, values)
                            dialog.submit(True)
                        except (DatabaseError, ValueError) as error:
                            message.text = str(error)
                        finally:
                            saving = False
                            for control in controls:
                                if hasattr(control, 'enable'):
                                    control.enable()

                    with ui.row().classes('w-full justify-end'):
                        cancel = ui.button('취소', on_click=lambda: dialog.submit(False)).props('flat')
                        save_button = ui.button('저장', icon='save', on_click=save)
            if await dialog:
                await self.reload()
        except (DatabaseError, ValueError) as error:
            ui.notify(str(error), type='negative')
        finally:
            self.editing = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()
