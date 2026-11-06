"""사용자 일정과 예약 상담 일지 추가 화면."""
from datetime import date, datetime, time, timedelta
from nicegui import run, ui
from pydantic import ValidationError
from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import CalendarEventInput
from maeumnarae.services.reports.reporting import KST
from maeumnarae.services.calendar.calendar_reservations import KINDS, reservation_options, save_reservation
from maeumnarae.views.calendar.calendar_reservation_fields import ReservationFields
from maeumnarae.views.journals.journal_defaults import default_duration_minutes
from maeumnarae.views.shared.delete_action import delete_button
from maeumnarae.views.shared.time_inputs import parse_time, time_input


async def open_event_editor(repository, calendars, selected, on_change, entry=None):
    if entry is not None and entry.source != 'custom':
        return
    opened_at = datetime.now(KST).replace(second=0, microsecond=0)
    sources = {item.id: item.source for item in calendars}
    options = {item.id: item.name for item in calendars
               if item.source == 'custom' or (entry is None and item.source == 'counseling')}
    if not options:
        ui.notify('먼저 일정 등록용 캘린더를 추가해 주세요.', type='info')
        return
    dialog = None
    try:
        local = entry.starts_at.astimezone(KST) if entry else datetime.combine(selected, time(9), KST)
        custom = [item for item in calendars if item.source == 'custom']
        default_calendar = next((item.id for item in custom if item.visible),
                                custom[0].id if custom else next(iter(options)))
        reservation_data = await run.io_bound(reservation_options, repository.database) if entry is None else ({}, {}, {})
        duration = await run.io_bound(default_duration_minutes, repository.database, fallback=50) if entry is None else 50
        with ui.context.client.content:
            with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-4xl p-6 max-h-[90vh] overflow-y-auto'):
                ui.label('일정 수정' if entry else '일정 추가').classes('text-xl font-bold')
                target = ui.select(options, label='캘린더', value=entry.calendar_id if entry else default_calendar).props('outlined').classes('w-full')
                if entry:
                    target.disable()
                title = ui.input('일정 제목', value=entry.title if entry else '').props('outlined maxlength=200').classes('w-full')
                with ui.row().classes('w-full flex-nowrap items-start') as time_row:
                    all_day = ui.checkbox('종일', value=entry.all_day if entry else False).classes('shrink-0 self-center')
                    day = ui.date_input('시작 날짜', value=str(local.date())).props('outlined').classes('flex-1 min-w-0')
                    start = time_input('시작 시간', value=local.strftime('%H:%M')).props('outlined').classes('flex-1 min-w-0')
                    end_time = local + timedelta(minutes=entry.duration_minutes if entry else 60)
                    end_date = (end_time - timedelta(microseconds=1)).date() if entry and entry.all_day else end_time.date()
                    separator = ui.label('~').classes('self-center shrink-0 text-slate-500')
                    end = time_input('종료 시간', value=end_time.strftime('%H:%M')).props('outlined').classes('flex-1 min-w-0')
                    end_day = ui.date_input('종료 날짜', value=str(end_date)).props('outlined').classes('flex-1 min-w-0')
                all_day_hint = ui.label('종일 일정은 시작 날짜부터 종료 날짜까지 포함합니다.').classes('text-xs text-slate-500')
                location = ui.input('장소', value=entry.location if entry else '').props('outlined maxlength=200').classes('w-full')
                reservation = ReservationFields(repository.database, reservation_data, opened_at, duration, time_row)
                content = ui.textarea('내용', value=entry.content if entry else '').props('outlined maxlength=20000').classes('w-full')
                message = ui.label().classes('text-sm text-red-700')
                with ui.row().classes('w-full justify-end'):
                    cancel = ui.button('취소').props('flat')
                    if entry:
                        async def after_deleted():
                            dialog.submit(False)
                            await on_change(None)
                        delete = delete_button(repository.database, 'event', lambda: entry, after_deleted, blocked=lambda: saving)
                    save = ui.button('일정 저장', icon='save')
        fields = (target, title, day, start, end, end_day, all_day, location, content, *reservation.fields)
        original = tuple(field.value for field in fields)
        saving = False

        previous_day = day.value

        def sync_end_day(event):
            nonlocal previous_day
            try:
                new_day = date.fromisoformat(event.value or '').isoformat()
            except ValueError:
                return
            if end_day.value == previous_day:
                end_day.value = new_day
            previous_day = new_day

        day.on_value_change(sync_end_day)

        def is_reservation():
            return entry is None and sources.get(target.value) == 'counseling'

        def update_time_fields():
            counseling = is_reservation()
            reservation.panel.set_visibility(counseling)
            reservation.start.set_visibility(counseling)
            reservation.duration.set_visibility(counseling)
            title.set_visibility(not counseling)
            content.set_visibility(not counseling)
            for element in (all_day, location, all_day_hint):
                element.set_visibility(not counseling)
            end_day.set_visibility(not counseling and all_day.value)
            for element in (start, end, separator):
                element.set_visibility(not counseling and not all_day.value)
            start.set_enabled(not saving and not all_day.value)
            end.set_enabled(not saving and not all_day.value)
            reservation.saving = saving
            reservation.update_visibility()

        all_day.on_value_change(update_time_fields)
        target.on_value_change(update_time_fields)
        update_time_fields()

        async def close():
            if saving:
                return
            if original != tuple(field.value for field in fields):
                with ui.dialog().props('persistent') as confirm, ui.card():
                    ui.label('저장하지 않은 내용을 버릴까요?')
                    ui.button('계속 작성', on_click=lambda: confirm.submit(False))
                    ui.button('변경 내용 버리기', on_click=lambda: confirm.submit(True))
                discard = await confirm
                confirm.delete()
                if not discard:
                    return
            dialog.submit(False)

        async def store():
            nonlocal saving
            if saving:
                return
            try:
                counseling = is_reservation()
                if counseling:
                    moment = datetime.combine(date.fromisoformat(day.value), parse_time(reservation.start.value), KST)
                    value = dict(**reservation.values(), title=KINDS[reservation.kind.value], starts_at=moment)
                else:
                    moment = datetime.combine(date.fromisoformat(day.value), time.min if all_day.value else parse_time(start.value), KST)
                    if not 2 <= moment.year <= 9998:
                        raise ValueError
                    final_day = date.fromisoformat(end_day.value) if all_day.value else moment.date()
                    if not 2 <= final_day.year <= 9998 or final_day < moment.date():
                        message.text = '종료 날짜는 시작 날짜 이후여야 합니다.'
                        return
                    ends_at = datetime.combine(final_day, time.min if all_day.value else parse_time(end.value), KST)
                    if not all_day.value and ends_at < moment:
                        message.text = '종료 시간은 시작 시간보다 이를 수 없습니다.'
                        return
                    if all_day.value or ends_at == moment:
                        ends_at += timedelta(days=1)
                    if ends_at <= moment:
                        message.text = '종료 날짜와 시간은 시작 날짜와 시간보다 이후여야 합니다.'
                        return
                    duration_minutes = (ends_at - moment).total_seconds() / 60
                    value = CalendarEventInput(calendar_id=target.value, title=title.value, starts_at=moment,
                                               duration_minutes=duration_minutes,
                                               all_day=all_day.value,
                                               location=location.value or '', content=content.value or '')
            except (ValueError, TypeError):
                message.text = ('학생·사례 등 연결 대상, 날짜·시작 시각, 시간(1~1,440분)을 확인해 주세요.' if is_reservation() else '캘린더, 제목(1~200자), 날짜·시작 시간·종료 시간, 장소(200자 이내), 내용(20,000자 이내)을 확인해 주세요.')
                return
            saving = True
            for field in (*fields, save, cancel):
                field.disable()
            if entry:
                delete.disable()
            try:
                if counseling:
                    await run.io_bound(save_reservation, repository.database, **value)
                else:
                    await run.io_bound(repository.save_event, value, entry.id if entry else None)
                dialog.submit(True)
            except ValidationError:
                message.text = '날짜·시작 시각, 시간(1~1,440분의 정수)을 확인해 주세요.'
            except (DatabaseError, ValueError, TypeError) as error:
                message.text = str(error)
            finally:
                saving = False
                for field in (*fields, save, cancel):
                    field.enable()
                if entry:
                    delete.enable()
                update_time_fields()
                if entry:
                    target.disable()

        cancel.on_click(close)
        save.on_click(store)
        if await dialog:
            await on_change(date.fromisoformat(day.value))
            ui.notify('예약 일지를 저장했습니다.' if is_reservation() else '일정을 저장했습니다.', type='positive')
    except DatabaseError as error:
        ui.notify(str(error), type='negative')
    finally:
        if dialog is not None and not dialog.is_deleted:
            dialog.delete()
