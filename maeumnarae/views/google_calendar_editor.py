"""Connection management and read-only details for Google calendars."""
from datetime import datetime, timedelta, timezone
from nicegui import run, ui
from pydantic import ValidationError

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import CalendarInput
from maeumnarae.repositories.google_calendar_repo import GoogleCalendarRepository, validate_url
from maeumnarae.services.google_calendar import download, events_from_ics
from maeumnarae.services.reporting import KST


def show_google_event(entry):
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg p-6'):
        ui.label(entry.title).classes('text-xl font-bold break-words')
        ui.label(f'{entry.calendar_name} · 구글 캘린더 · 읽기 전용')
        first = entry.starts_at.astimezone(KST)
        end = first + timedelta(minutes=entry.duration_minutes)
        if entry.all_day:
            ui.label(f'{first:%Y.%m.%d} ~ {end - timedelta(days=1):%Y.%m.%d} · 종일')
        else:
            ui.label(f'{first:%Y.%m.%d %H:%M} ~ {end:%Y.%m.%d %H:%M} (한국 시간)')
        if entry.location:
            ui.label(entry.location).classes('whitespace-pre-wrap break-words')
        ui.label(entry.content).classes('whitespace-pre-wrap break-words')
        ui.label('일정 변경은 구글 캘린더에서 해 주세요.').classes('text-sm text-slate-500')
        ui.button('닫기', on_click=dialog.close).props('flat')
    dialog.open()


async def edit_google_calendar(database, item=None):
    repository = GoogleCalendarRepository(database)
    subscription_id = -item.id - 2 if item else None
    row = await run.io_bound(repository.get, subscription_id) if item else None
    if item and row is None:
        return False
    dialog = None
    try:
        with ui.context.client.content:
            with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-lg p-6'):
                ui.label('구글 캘린더 연결 수정' if item else '구글 캘린더 연결').classes('text-xl font-bold')
                name = ui.input('캘린더 이름', value=item.name if item else '구글 캘린더').props('outlined maxlength=100').classes('w-full')
                color = ui.color_input('색상', value=item.color if item else '#4285f4', preview=True).classes('w-full')
                color.picker.q_color.props('format-model=hex')
                address = ui.input('비공개 iCal 주소', value=row['url'] if row else '', password=True,
                                   password_toggle_button=True).props('outlined').classes('w-full')
                ui.label('구글 캘린더 설정 → 캘린더 통합 → iCal 형식의 비공개 주소를 붙여 넣으세요.').classes('text-sm')
                ui.label('주소로 일정에 접근할 수 있으므로 다른 사람에게 공유하지 마세요. 주소와 일정은 암호화된 DB에 저장됩니다.').classes('text-xs text-slate-500')
                message = ui.label().classes('text-sm text-red-700')
                with ui.row().classes('w-full justify-end'):
                    cancel = ui.button('취소', on_click=lambda: dialog.submit(False)).props('flat')
                    save = ui.button('연결 확인 후 저장', icon='link')
        saving = False

        async def submit():
            nonlocal saving
            if saving:
                return
            try:
                value = CalendarInput(name=name.value.strip(), color=color.value)
                url = validate_url(address.value)
            except ValidationError:
                message.text = '캘린더 이름(1~100자)과 색상(#RRGGBB)을 확인해 주세요.'
                return
            except ValueError as error:
                message.text = str(error)
                return
            saving = True
            for control in (name, color, address, cancel, save):
                control.disable()
            message.text = '연결을 확인하고 있습니다…'
            try:
                def check_and_save():
                    raw = download(url)
                    today = datetime.now(KST).date()
                    events_from_ics(raw, {'id': subscription_id or 0, 'name': value.name, 'color': value.color},
                                    today - timedelta(days=31), today + timedelta(days=366))
                    repository.save(value, url, raw, datetime.now(timezone.utc).isoformat(), subscription_id)
                await run.io_bound(check_and_save)
                dialog.submit(True)
            except (ValueError, DatabaseError) as error:
                message.text = str(error)
            finally:
                saving = False
                for control in (name, color, address, cancel, save):
                    control.enable()
        save.on_click(submit)
        return bool(await dialog)
    finally:
        if dialog is not None and not dialog.is_deleted:
            dialog.delete()
