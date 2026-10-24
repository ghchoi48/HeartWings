"""캘린더 저장, 선택 필터 및 월간/주간 탐색 검증."""
import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database, NotFoundError, SCHEMA_VERSION
from maeumnarae.core.models import CalendarInput, CalendarEventInput, CounselingInput, StudentInput
from maeumnarae.services.reporting import KST
from maeumnarae.repositories.calendar_repo import CalendarRepository
from maeumnarae.repositories.counseling_repo import CounselingRepository
from maeumnarae.repositories.reporting_repo import ReportingRepository
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.views.calendar_view import CalendarView


@pytest.fixture
def data(tmp_path):
    db = Database('test-only', tmp_path / 'calendar.db')
    db.initialize()
    repo = CalendarRepository(db)
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    counseling = CounselingRepository(db).create(CounselingInput(student_id=student.id, title='상담',
        starts_at=datetime(2026, 10, 20, 9, tzinfo=KST)))
    custom = repo.create(CalendarInput(name='학교 일정', color='#2563eb'))
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='회의',
        starts_at=datetime(2026, 10, 20, 10, tzinfo=KST), duration_minutes=30))
    return db, repo, custom, counseling


def test_calendar_storage_filtering_and_reinitialize(data):
    db, repo, custom, counseling = data
    calendars = repo.list()
    assert calendars[0].source == 'counseling'
    day = date(2026, 10, 20)
    assert repo.events(day, day, []) == []
    all_events = repo.events(day, day, [c.id for c in calendars])
    assert [entry.title for entry in all_events] == ['상담', '회의']
    assert all_events[0].source == 'counseling'
    assert all_events[0].id == counseling.id
    assert [entry.title for entry in repo.events(day, day, [custom.id])] == ['회의']
    assert repo.events(day, day, [custom.id], 'completed') == []
    repo.set_visible(custom.id, False)
    db.initialize()
    assert not repo.list()[1].visible
    event = all_events[1]
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='변경한 회의',
        starts_at=datetime(2026, 10, 21, 0, tzinfo=KST)), event.id)
    assert repo.events(day, day, [custom.id]) == []
    assert repo.events(date(2026, 10, 21), date(2026, 10, 21), [custom.id])[0].title == '변경한 회의'
    with pytest.raises(NotFoundError):
        repo.save_event(CalendarEventInput(calendar_id=calendars[0].id, title='연동 캘린더에 직접 저장 불가',
            starts_at=datetime(2026, 10, 20, 9, tzinfo=KST)))
    db.initialize()
    assert len(repo.list()) == 3
    assert len(repo.events(date(2026, 10, 21), date(2026, 10, 21), [custom.id])) == 1


def test_events_without_status_preserve_records_on_reinitialize(data):
    db, repo, custom, counseling = data
    assert 'status' not in CalendarEventInput.model_fields
    with db.session(write=True) as connection:
        assert 'status' not in {row['name'] for row in connection.execute('PRAGMA table_info(calendar_events)')}
        original = dict(connection.execute('SELECT * FROM calendar_events').fetchone())
    db.initialize()
    db.initialize()  # 재실행해도 데이터나 스키마를 바꾸지 않는다.
    with db.session() as connection:
        saved = dict(connection.execute('SELECT * FROM calendar_events').fetchone())
        assert saved == original
        assert connection.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    day = date(2026, 10, 20)
    event = repo.events(day, day, [custom.id])[0]
    assert event.status is None
    assert CounselingRepository(db).get(counseling.id).status == 'scheduled'
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='수정 일정', starts_at=event.starts_at), event.id)
    assert repo.events(day, day, [custom.id])[0].title == '수정 일정'


def test_special_education_calendar_sync_and_open(data):
    from maeumnarae.core.models import SpecialEducationInput
    from maeumnarae.repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
    from maeumnarae.repositories.deletion_repo import DeletionRepository
    from maeumnarae.views.app_layout import AppLayout

    db, repo, _, counseling = data
    case = SpecialEducationRepository(db).save(SpecialEducationInput(
        student_id=counseling.student_id, title='특별교육', law='교원지위법'))
    logs = SpecialEducationLogRepository(db)
    value = CounselingInput(student_id=counseling.student_id, case_id=case.id,
        title='비공개 일지 제목', starts_at=datetime(2026, 10, 20, 23, 30, tzinfo=KST), duration_minutes=90)
    log = logs.create(value)
    calendar = next(c for c in repo.list() if c.source == 'counseling')
    day = date(2026, 10, 21)
    entry = repo.events(day, day, [calendar.id])[0]
    assert entry.source == 'special_education'
    assert entry.id == log.id and entry.owner_id == counseling.student_id
    assert entry.display_name == '학생 · 특별교육'
    assert not entry.content
    assert repo.events(day, day, [calendar.id], 'completed') == []
    logs.update(log.id, value.model_copy(update={'status': 'completed'}))
    assert repo.events(day, day, [calendar.id], 'completed')[0].status == 'completed'

    async def check():
        with Client(page('/special-calendar-test')):
            layout = AppLayout(Mock(), Mock(), Mock())
            layout.navigate = Mock()
            layout.special_education_view = SimpleNamespace(open_record=AsyncMock())
            view = CalendarView(ReportingRepository(db), AsyncMock(), layout.open_linked_schedule)
            await view.open_event(entry)
            layout.navigate.assert_called_once_with('special_education')
            layout.special_education_view.open_record.assert_awaited_once_with(log.id)
            assert not layout.opening_schedule
    asyncio.run(check())
    DeletionRepository(db).delete('special_log', log.id)
    assert repo.events(day, day, [calendar.id]) == []


def test_calendar_selection_navigation_and_open(data):
    db, repo, custom, counseling = data

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/calendar-view-test')):
            on_open = AsyncMock()
            view = CalendarView(ReportingRepository(db), on_open)
            view.anchor = view.selected = date(2026, 10, 20)
            with patch('maeumnarae.views.calendar_view.ui.timer'):
                view.build()
            with patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
                await view.reload()
                assert len(view.calendars) == 3
                assert len(view.events_by_day[view.selected]) == 2
                checkboxes = [item for item in view.calendar_list.descendants() if isinstance(item, ui.checkbox)]
                assert len(checkboxes) == 3
                assert all(item.value for item in checkboxes)
                await view.toggle_calendar(custom.id, False)
                assert len(view.events_by_day[view.selected]) == 1
                await view.open_event(view.events_by_day[view.selected][0])
                on_open.assert_awaited_once_with(counseling.id)
                await view.toggle_calendar(view.calendars[0].id, False)
                assert not view.events_by_day
                await view.toggle_calendar(-1, False)
                assert '표시할 캘린더' in view.message.text
                await view.shift(1)
                assert view.anchor == date(2026, 11, 1)
                await view.shift(-1)
                assert view.anchor == date(2026, 10, 1)
                # UI 이벤트 자동 실행 없이 주간 모드 설정 후 이동을 검증한다.
                view.mode = SimpleNamespace(value='week')
                await view.shift(-1)
                assert view.anchor == date(2026, 9, 24)
                view.anchor = view.selected = date(2026, 12, 31)
                await view.shift(1)
                assert view.selected == date(2027, 1, 7)
                assert view.previous_button.text == '이전 주'
                await view.today()
                assert view.selected == datetime.now(KST).date()
    asyncio.run(check())


def test_slow_response_cannot_replace_new_calendar_selection():
    async def check():
        with Client(page('/calendar-stale-test')):
            view = CalendarView(Mock(), AsyncMock())
            with patch('maeumnarae.views.calendar_view.ui.timer'):
                view.build()
            repo = Mock()
            repo.list.return_value = []
            repo.events.return_value = []
            view.repository = repo
            started, release = asyncio.Event(), asyncio.Event()
            calls = 0

            async def invoke(function, *args, **kwargs):
                nonlocal calls
                if function is repo.list:
                    calls += 1
                    if calls == 1:
                        started.set()
                        await release.wait()
                return function(*args, **kwargs)

            with patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
                first = asyncio.create_task(view.reload())
                await started.wait()
                view.anchor = view.selected = date(2027, 1, 1)
                await view.reload()
                release.set()
                await first
                assert view.heading.text == '2027년 01월'
                repo.events.assert_called_once()
    asyncio.run(check())


def test_sunday_start_and_korean_holidays():
    from maeumnarae.services.calendar_holidays import korean_holidays, is_day_off
    from maeumnarae.views.calendar_view import visible_days

    assert visible_days(date(2026, 1, 1), 'week') == [date(2025, 12, 28), date(2025, 12, 29),
        date(2025, 12, 30), date(2025, 12, 31), date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    assert visible_days(date(2026, 3, 1), 'month')[0] == date(2026, 3, 1)
    days = korean_holidays(date(2026, 3, 1), date(2026, 3, 7))
    assert days[date(2026, 3, 1)] == '삼일절'
    assert '대체' in days[date(2026, 3, 2)]
    assert is_day_off(date(2026, 3, 2), days)
    assert is_day_off(date(2026, 3, 7), days)
    assert not is_day_off(date(2026, 3, 3), days)
    cross_year = korean_holidays(date(2025, 12, 25), date(2026, 1, 2))
    assert date(2025, 12, 25) in cross_year and date(2026, 1, 1) in cross_year


def test_holiday_calendar_visibility_and_date_colors(data):
    from maeumnarae.services.calendar_holidays import HOLIDAY_CALENDAR_ID, HOLIDAY_COLOR
    db, repo, _, _ = data
    holiday = next(item for item in repo.list() if item.source == 'holidays')
    assert holiday.visible and holiday.color == HOLIDAY_COLOR

    async def check():
        with Client(page('/holiday-calendar-test')):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.anchor = view.selected = date(2026, 3, 2)
            with patch('maeumnarae.views.calendar_view.ui.timer'):
                view.build()

            async def invoke(function, *args, **kwargs):
                return function(*args, **kwargs)

            with patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
                await view.reload()
                labels = [item.text for item in view.grid.descendants() if isinstance(item, ui.label)]
                assert labels[:7] == ['일', '월', '화', '수', '목', '금', '토']
                assert '삼일절 대체 휴일' in labels
                buttons = {item.text: item for item in view.grid.descendants() if isinstance(item, ui.button)}
                assert buttons['3/2']._props['color'] == 'red-7'
                assert buttons['3/7']._props['color'] == 'red-7'
                assert buttons['3/3']._props['color'] != 'red-7'
                await view.toggle_calendar(HOLIDAY_CALENDAR_ID, False)
                labels = [item.text for item in view.grid.descendants() if isinstance(item, ui.label)]
                assert '삼일절 대체 휴일' not in labels
                buttons = {item.text: item for item in view.grid.descendants() if isinstance(item, ui.button)}
                assert buttons['3/2']._props['color'] == 'red-7'
    asyncio.run(check())
    db.initialize()
    assert not next(item for item in repo.list() if item.source == 'holidays').visible
    assert len([item for item in repo.list() if item.source == 'holidays']) == 1


def test_calendar_automatically_reflects_committed_event_changes(data):
    db, _, _, counseling = data

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/calendar-auto-refresh-test')), patch('maeumnarae.views.calendar_view.ui.timer'), \
                patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.anchor = view.selected = date(2026, 10, 20)
            view.build()
            await view.reload()
            assert view.previous_button.text == '이전 달'
            assert view.next_button.text == '다음 달'
            assert not hasattr(view, 'date_input')
            assert not hasattr(view, 'status')
            with patch.object(view, 'reload', new=AsyncMock()) as reload:
                await view.refresh_if_changed()
                reload.assert_not_awaited()
            repo = CounselingRepository(db)
            value = CounselingInput(**counseling.model_dump(include=set(CounselingInput.model_fields)))
            added = repo.create(value.model_copy(update={'title': '추가 일정'}))
            await view.refresh_if_changed()
            assert any(e.id == added.id and e.source == 'counseling'
                       for e in view.events_by_day[view.selected])
            for status, icon in [('scheduled', 'schedule'), ('completed', 'check_circle'), ('cancelled', 'cancel')]:
                repo.update(added.id, value.model_copy(update={'title': '변경 일정', 'status': status}))
                view.editor_open = True
                revision = view.loaded_revision
                await view.refresh_if_changed()
                assert view.loaded_revision == revision
                view.editor_open = False
                await view.refresh_if_changed()
                entry = next(e for e in view.events_by_day[view.selected]
                             if e.id == added.id and e.source == 'counseling')
                assert entry.status == status and entry.title == '변경 일정'
                assert any(isinstance(e, ui.icon) and e.props.get('name') == icon
                           for e in view.grid.descendants())
            repo.delete(added.id)
            await view.refresh_if_changed()
            assert not any(e.id == added.id and e.source == 'counseling'
                           for e in view.events_by_day[view.selected])
    asyncio.run(check())


def test_unified_counseling_calendar_names_filtering_and_open(data):
    from maeumnarae.core.models import GroupCounselingInput, GroupLogInput, TeacherInput, ConsultationInput
    from maeumnarae.repositories.group_counseling_repo import GroupCounselingRepository
    from maeumnarae.repositories.teacher_repo import TeacherRepository
    from maeumnarae.repositories.consultation_repo import ConsultationRepository

    db, repo, _, _ = data
    groups = GroupCounselingRepository(db)
    group = groups.save(GroupCounselingInput(name='친구 집단'))
    groups.save_log(GroupLogInput(group_id=group.id, title='집단 제목 숨김',
                                 starts_at=datetime(2026, 10, 20, 11, tzinfo=KST)))
    teacher = TeacherRepository(db).create_many([TeacherInput(name='김교사')])[0]
    ConsultationRepository(db).save(ConsultationInput(teacher_id=teacher.id, title='자문 제목 숨김',
                                   starts_at=datetime(2026, 10, 20, 12, tzinfo=KST)))
    calendar = next(c for c in repo.list() if c.source == 'counseling')
    assert calendar.name == '상담 일정'
    day = date(2026, 10, 20)
    entries = repo.events(day, day, [calendar.id])
    assert [e.source for e in entries] == ['counseling', 'group', 'consultation']
    assert [e.display_name for e in entries] == ['학생', '친구 집단', '김교사']
    assert all(e.calendar_name == '상담 일정' for e in entries)
    assert repo.events(date(2026, 10, 21), date(2026, 10, 21), [calendar.id]) == []

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/unified-calendar-test')), patch('maeumnarae.views.calendar_view.ui.timer'), \
                patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
            linked = AsyncMock()
            view = CalendarView(ReportingRepository(db), AsyncMock(), linked)
            view.anchor = view.selected = day
            view.build()
            await view.reload()
            texts = [e.text for e in view.grid.descendants() if isinstance(e, ui.label)]
            assert '09:00 학생' in texts
            assert '11:00 친구 집단' in texts
            assert '12:00 김교사' in texts
            assert '10:00 회의' in texts
            assert not any('제목 숨김' in text for text in texts)
            for entry in entries[1:]:
                await view.open_event(entry)
                linked.assert_awaited_with(entry)
            await view.toggle_calendar(calendar.id, False)
            assert all(e.source == 'custom' for e in view.events_by_day[day])
    asyncio.run(check())


def test_event_location_content_persistence_and_reinitialize(data):
    db, repo, custom, _ = data
    day = date(2026, 10, 20)
    entry = repo.events(day, day, [custom.id])[0]
    db.initialize()
    original = repo.events(day, day, [custom.id])[0]
    assert original.location == original.content == ''
    assert original.title == entry.title
    value = CalendarEventInput(calendar_id=custom.id, title='장소 있는 일정',
                               starts_at=datetime(2026, 10, 20, 13, tzinfo=KST),
                               location='상담실', content='첫 번째 줄\n두 번째 줄')
    repo.save_event(value)
    created = repo.events(day, day, [custom.id])[-1]
    assert (created.location, created.content) == ('상담실', '첫 번째 줄\n두 번째 줄')
    repo.save_event(value.model_copy(update={'location': '도서관', 'content': '수정 내용'}), created.id)
    db.initialize()
    updated = repo.events(day, day, [custom.id])[-1]
    assert (updated.location, updated.content) == ('도서관', '수정 내용')
    repo.save_event(value.model_copy(update={'location': '', 'content': ''}), created.id)
    cleared = repo.events(day, day, [custom.id])[-1]
    assert cleared.location == cleared.content == ''


@pytest.mark.parametrize('all_day', [False, True])
@pytest.mark.parametrize('start_time,end_time,minutes,days', [('09:00', '10:30', 90, 0), ('23:30', '23:45', 15, 1), ('09:00', '09:00', 1440, 1), ('09:00', '10:30', 90, 3)])
def test_event_editor_saves_and_restores_location_content(data, all_day, start_time, end_time, minutes, days):
    import inspect
    db, repo, custom, _ = data
    day = date(2026, 10, 20)

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/event-details-editor-test')), patch('maeumnarae.views.calendar_view.ui.timer'), \
                patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.anchor = view.selected = day
            view.build()
            await view.reload()

            async def create(dialog):
                fields = {e.props.get('label'): e for e in dialog.descendants()
                          if isinstance(e, (ui.input, ui.textarea))}
                toggle = next(e for e in dialog.descendants() if isinstance(e, ui.checkbox))
                controls = {e.props.get('label'): e for e in dialog.descendants() if e.props.get('label')}
                assert '상태' not in controls
                row_labels = [e.props.get('label') for e in controls['시작 날짜'].parent_slot.children
                              if e.props.get('label') and not isinstance(e, ui.checkbox)]
                assert row_labels == ['시작 날짜', '시작 시간', '종료 시간', '종료 날짜']
                controls['시작 날짜'].value = str(day + timedelta(days=1))
                assert controls['종료 날짜'].value == str(day + timedelta(days=1))
                controls['시작 날짜'].value = str(day)
                assert controls['종료 날짜'].value == str(day)
                controls['종료 날짜'].value = str(day + timedelta(days=3))
                controls['시작 날짜'].value = str(day + timedelta(days=1))
                assert controls['종료 날짜'].value == str(day + timedelta(days=3))
                controls['시작 날짜'].value = str(day)
                controls['종료 날짜'].value = str(day + timedelta(days=days))
                controls['시작 시간'].value = start_time
                controls['종료 시간'].value = end_time
                assert controls['시작 날짜'].parent_slot is controls['시작 시간'].parent_slot
                assert controls['시작 날짜'].parent_slot is controls['종료 시간'].parent_slot
                toggle.value = True
                toggle.value = all_day
                if not all_day and days == 0:
                    controls['종료 날짜'].value = ''  # Hidden date must not be parsed or saved.
                timed = [e for e in dialog.descendants() if e.props.get('label') in ('시작 시간', '종료 시간')]
                assert all(e.enabled == (not all_day) for e in timed)
                fields['일정 제목'].value = '상세 일정'
                fields['장소'].value = '상담실'
                fields['내용'].value = '준비물 안내\n회의 내용'
                button = next(e for e in dialog.descendants()
                              if isinstance(e, ui.button) and e.text == '일정 저장')
                handler = next(listener.handler for listener in button._event_listeners.values()
                               if listener.type == 'click')
                await inspect.getclosurevars(handler).nonlocals['callback']()
                assert dialog.submitted.is_set()
                return dialog._result

            with patch.object(ui.dialog, '__await__', lambda dialog: create(dialog).__await__()):
                await view.open_event_editor()
            saved = next(e for e in repo.events(day, day, [custom.id]) if e.title == '상세 일정')
            assert saved.all_day == all_day
            captions = [e.text for e in view.grid.descendants() if isinstance(e, ui.label)]
            assert ('상세 일정' if all_day else f'{start_time} 상세 일정') in captions
            if all_day:
                assert saved.starts_at.astimezone(KST).hour == 0
                assert saved.duration_minutes == 1440 * (days + 1)
            assert saved.duration_minutes == (1440 * (days + 1) if all_day else minutes)
            assert saved.location == '상담실'
            assert saved.content == '준비물 안내\n회의 내용'

            async def reopen(dialog):
                fields = {e.props.get('label'): e for e in dialog.descendants()
                          if isinstance(e, (ui.input, ui.textarea))}
                toggle = next(e for e in dialog.descendants() if isinstance(e, ui.checkbox))
                assert toggle.value == all_day
                if not all_day:
                    from maeumnarae.views.time_inputs import parse_time
                    controls = {e.props.get('label'): e for e in dialog.descendants() if e.props.get('label')}
                    assert parse_time(controls['시작 시간'].value).strftime('%H:%M') == start_time
                    assert parse_time(controls['종료 시간'].value).strftime('%H:%M') == end_time
                toggle.value = not all_day
                timed = [e for e in dialog.descendants() if e.props.get('label') in ('시작 시간', '종료 시간')]
                assert all(e.enabled == all_day for e in timed)
                assert fields['장소'].value == saved.location
                assert fields['내용'].value == saved.content
                return False

            with patch.object(ui.dialog, '__await__', lambda dialog: reopen(dialog).__await__()):
                await view.open_event_editor(saved)
    asyncio.run(check())


def test_all_day_reinitialize_preserves_existing_events(data):
    db, repo, custom, _ = data
    day = date(2026, 10, 20)
    previous = repo.events(day, day, [custom.id])
    db.initialize()
    assert repo.events(day, day, [custom.id]) == previous
    assert not previous[0].all_day


def test_multiday_calendar_overlap_and_midnight_boundary(data):
    db, repo, custom, _ = data
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='월 경계 일정',
        starts_at=datetime(2026, 10, 30, 9, tzinfo=KST), duration_minutes=3 * 1440 + 60))
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='종일 여러 날짜', all_day=True,
        starts_at=datetime(2026, 10, 30, tzinfo=KST), duration_minutes=3 * 1440))
    first = date(2026, 11, 1)
    assert len(repo.events(first, first, [custom.id])) == 2
    assert [e.title for e in repo.events(date(2026, 11, 2), date(2026, 11, 2), [custom.id])] == ['월 경계 일정']
    assert repo.events(date(2026, 11, 3), date(2026, 11, 3), [custom.id]) == []
    db.initialize()

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/multiday-calendar-test')), patch('maeumnarae.views.calendar_view.ui.timer'), \
                patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.anchor = view.selected = first
            view.build()
            await view.reload()
            assert len(view.events_by_day[first]) == 2
            assert len(view.events_by_day[date(2026, 11, 2)]) == 1
            assert not view.events_by_day.get(date(2026, 11, 3))
            texts = [e.text for e in view.grid.descendants() if isinstance(e, ui.label)]
            assert '계속 · 월 경계 일정' not in texts
            assert '종일 여러 날짜' not in texts
            bars = [e for e in view.grid.descendants() if isinstance(e, ui.button)]
            assert any(e.props.get('aria-label') == '종일 여러 날짜' for e in bars)
    asyncio.run(check())


def test_multiday_bars_span_columns_and_show_title_once(data):
    from maeumnarae.views.calendar_view import week_event_segments, visible_days
    db, repo, custom, _ = data
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='연결 일정', all_day=True,
        starts_at=datetime(2026, 10, 22, tzinfo=KST), duration_minutes=6 * 1440))
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='겹친 일정', all_day=True,
        starts_at=datetime(2026, 10, 23, tzinfo=KST), duration_minutes=2 * 1440))

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/connected-bars-test')), patch('maeumnarae.views.calendar_view.ui.timer'), \
                patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.anchor = view.selected = date(2026, 10, 22)
            view.build()
            await view.reload()
            texts = [e.text for e in view.grid.descendants() if isinstance(e, ui.label)]
            assert texts.count('연결 일정') == 1
            assert texts.count('겹친 일정') == 1
            bars = [e for e in view.grid.descendants() if isinstance(e, ui.button)
                    and e.props.get('aria-label') == '연결 일정']
            assert len(bars) == 2
            assert all(e.props.get('unelevated') for e in bars)
            week = visible_days(date(2026, 10, 22), 'week')
            segments = week_event_segments(week, view.events_by_day)
            first = next(s for s in segments if s[0].title == '연결 일정')
            overlap = next(s for s in segments if s[0].title == '겹친 일정')
            assert first[1:3] == (4, 3)
            assert first[4:] == (True, False)
            assert first[3] != overlap[3]
            next_week = visible_days(date(2026, 10, 25), 'week')
            continuation = week_event_segments(next_week, view.events_by_day)[0]
            assert continuation[1:3] == (0, 3)
            assert continuation[4:] == (False, True)
    asyncio.run(check())


@pytest.mark.parametrize('hide_sat,hide_sun', [(False, False), (True, False), (False, True), (True, True)])
def test_hide_weekend_days_independently(data, hide_sat, hide_sun):
    from maeumnarae.views.calendar_view import visible_days, week_event_segments
    db, repo, custom, _ = data
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='주말 연결', all_day=True,
        starts_at=datetime(2026, 10, 18, tzinfo=KST), duration_minutes=7 * 1440))

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/weekend-visibility-test')), patch('maeumnarae.views.calendar_view.ui.timer'), \
                patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.anchor = view.selected = date(2026, 10, 20)
            view.build()
            await view.reload()
            view.hide_saturday.value = hide_sat
            view.hide_sunday.value = hide_sun
            for mode in ('month', 'week'):
                view.mode = SimpleNamespace(value=mode)
                view.render_grid()
                labels = [e.text for e in view.grid.descendants() if isinstance(e, ui.label)]
                assert ('토' not in labels) == hide_sat
                assert ('일' not in labels) == hide_sun
                buttons = [e.text.removesuffix(' · 오늘') for e in view.grid.descendants() if isinstance(e, ui.button)]
                assert ('10/24' not in buttons) == hide_sat
                assert ('10/18' not in buttons) == hide_sun
                assert '10/20' in buttons
            days = [d for d in visible_days(view.anchor, 'week')
                    if not (hide_sat and d.weekday() == 5) and not (hide_sun and d.weekday() == 6)]
            segment = next(s for s in week_event_segments(days, view.events_by_day) if s[0].title == '주말 연결')
            assert segment[1:3] == (0, 7 - hide_sat - hide_sun)
            await view.reload()
            assert view.hide_saturday.value == hide_sat
            assert view.hide_sunday.value == hide_sun
            view.hide_saturday.value = view.hide_sunday.value = False
            labels = [e.text for e in view.grid.descendants() if isinstance(e, ui.label)]
            assert '토' in labels and '일' in labels
    asyncio.run(check())


def test_event_editor_rejects_end_before_start_and_allows_correction(data):
    import inspect
    db, repo, custom, _ = data

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/event-invalid-time-test')), patch('maeumnarae.views.calendar_view.ui.timer'), \
                patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.anchor = view.selected = date(2026, 10, 20)
            view.build()
            await view.reload()

            async def interact(dialog):
                controls = {e.props.get('label'): e for e in dialog.descendants() if e.props.get('label')}
                controls['일정 제목'].value = '시간 검증'
                controls['시작 시간'].value = '10:00'
                controls['종료 시간'].value = '09:00'
                button = next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == '일정 저장')
                handler = next(listener.handler for listener in button._event_listeners.values() if listener.type == 'click')
                save = inspect.getclosurevars(handler).nonlocals['callback']
                with patch.object(view.repository, 'save_event', wraps=repo.save_event) as persist:
                    await save()
                    persist.assert_not_called()
                    assert not dialog.submitted.is_set()
                    assert button.enabled
                    assert any(isinstance(e, ui.label) and e.text == '종료 시간은 시작 시간보다 이를 수 없습니다.'
                               for e in dialog.descendants())
                    controls['종료 시간'].value = '11:30'
                    await save()
                    persist.assert_called_once()
                    assert persist.call_args.args[0].duration_minutes == 90
                return dialog._result

            with patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()):
                await view.open_event_editor()
    asyncio.run(check())


def test_custom_calendar_update_delete_and_protected_calendars(data):
    db, repo, custom, counseling = data
    day = date(2026, 10, 20)
    repo.set_visible(custom.id, False)
    repo.update(custom.id, CalendarInput(name='수정한 일정', color='#db2777'))
    saved = next(item for item in repo.list() if item.id == custom.id)
    assert (saved.name, saved.color, saved.visible) == ('수정한 일정', '#db2777', False)
    assert repo.events(day, day, [custom.id])[0].calendar_name == '수정한 일정'
    for item in repo.list():
        if item.source != 'custom':
            with pytest.raises(NotFoundError):
                repo.update(item.id, CalendarInput(name='변경 불가'))
            with pytest.raises(NotFoundError):
                repo.delete(item.id)
    repo.delete(custom.id)
    assert all(item.id != custom.id for item in repo.list())
    with db.session() as connection:
        assert not connection.execute('SELECT id FROM calendar_events WHERE calendar_id=?', (custom.id,)).fetchall()
    assert CounselingRepository(db).get(counseling.id) is not None
    with pytest.raises(NotFoundError):
        repo.delete(custom.id)


def test_calendar_edit_and_delete_dialogs(data):
    import inspect
    db, repo, custom, _ = data

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def click(dialog, text):
        button = next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == text)
        handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
        await inspect.getclosurevars(handler).nonlocals['callback']()
        return dialog._result

    async def check():
        with Client(page('/calendar-management-test')), patch('maeumnarae.views.calendar_view.ui.timer'), patch(
                'maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.build()
            await view.reload()
            buttons = [e for e in view.calendar_list.descendants() if isinstance(e, ui.button)]
            assert len(buttons) == 2  # Only the custom calendar gets management buttons.

            async def edit(dialog):
                fields = {e.props.get('label'): e for e in dialog.descendants() if e.props.get('label')}
                assert fields['캘린더 이름'].value == custom.name
                fields['캘린더 이름'].value = '새 이름'
                fields['색상'].value = '#db2777'
                return await click(dialog, '저장')

            with patch.object(ui.dialog, '__await__', lambda dialog: edit(dialog).__await__()):
                await view.open_calendar_editor(custom)
            assert next(c for c in view.calendars if c.id == custom.id).name == '새 이름'
            assert not view.editor_open

            async def cancel(dialog):
                return False

            with patch.object(ui.dialog, '__await__', lambda dialog: cancel(dialog).__await__()):
                await view.delete_calendar(custom)
            assert any(c.id == custom.id for c in repo.list())
            with patch.object(ui.dialog, '__await__', lambda dialog: click(dialog, '삭제').__await__()):
                await view.delete_calendar(custom)
            assert all(c.id != custom.id for c in view.calendars)
            assert not view.add_event.enabled
            assert not view.editor_open
    asyncio.run(check())


@pytest.mark.parametrize('editing', [False, True])
def test_calendar_color_picker_saves_custom_color(data, editing):
    import inspect
    from nicegui.events import ColorPickEventArguments

    db, repo, custom, _ = data
    picked_color = '#12ab34'

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/calendar-color-picker-test')), patch('maeumnarae.views.calendar_view.ui.timer'), patch(
                'maeumnarae.views.calendar_view.run.io_bound', side_effect=invoke):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.build()

            async def interact(dialog):
                color = next(e for e in dialog.descendants() if isinstance(e, ui.color_input))
                assert color.preview
                assert color.picker.q_color.props['format-model'] == 'hex'
                assert color.value == (custom.color if editing else '#2563eb')
                color.open_picker()
                assert color.picker.q_color.props['model-value'] == color.value
                name = next(e for e in dialog.descendants()
                            if isinstance(e, ui.input) and e.props.get('label') == '캘린더 이름')
                name.value = '자유 색상 캘린더'
                button = next(e for e in dialog.descendants()
                              if isinstance(e, ui.button) and e.text == ('저장' if editing else '추가'))
                handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
                save = inspect.getclosurevars(handler).nonlocals['callback']
                color.value = 'invalid'
                await save()
                assert not dialog.submitted.is_set()
                assert button.enabled
                event = ColorPickEventArguments(sender=color.picker, client=ui.context.client, color=picked_color)
                for callback in color.picker._pick_handlers:
                    callback(event)
                assert color.value == picked_color
                color.picker.close()
                await save()
                assert dialog.submitted.is_set()
                return dialog._result

            with patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()):
                await view.open_calendar_editor(custom if editing else None)
            saved = next(c for c in repo.list() if c.name == '자유 색상 캘린더')
            assert saved.color == picked_color
            assert (saved.id == custom.id) == editing
            assert next(c for c in view.calendars if c.id == saved.id).color == picked_color
    asyncio.run(check())
