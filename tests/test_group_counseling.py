"""집단별 저장 격리, 선택 응답 순서와 화면 구성을 검증한다."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import ConflictError, Database, NotFoundError
from maeumnarae.core.models import GroupCounseling, GroupCounselingInput, GroupLogInput
from maeumnarae.repositories.group_counseling_repo import GroupCounselingRepository
from maeumnarae.views.group_counseling_view import GroupCounselingView


def test_group_and_log_persistence(tmp_path):
    db = Database('test-groups', tmp_path / 'groups.db')
    db.initialize()
    repo = GroupCounselingRepository(db)
    first = repo.save(GroupCounselingInput(name='사회성 집단', participants='가상 학생 1, 2', purpose='관계 형성'))
    second = repo.save(GroupCounselingInput(name='진로 집단'))
    value = GroupLogInput(group_id=first.id, title='첫 만남', starts_at=datetime.now(timezone.utc), content_html='<h2>활동</h2><p>내용</p>')
    entry = repo.save_log(value)
    assert repo.get(first.id) == first
    assert repo.list_logs(first.id) == [entry]
    assert repo.list_logs(second.id) == []
    with pytest.raises(NotFoundError):
        repo.save_log(value.model_copy(update={'group_id': second.id}), entry.id)
    with pytest.raises(ConflictError):
        repo.save_log(value.model_copy(update={'group_id': 999}))
    updated = repo.save_log(value.model_copy(update={'title': '수정한 일지'}), entry.id)
    assert updated.created_at == entry.created_at
    assert repo.get_log(entry.id).title == '수정한 일지'
    repo.save(GroupCounselingInput(name='사회성 집단 수정'), first.id)
    assert repo.list_logs(first.id)[0].content_html == value.content_html
    reopened = Database('test-groups', db.path)
    reopened.initialize()
    assert GroupCounselingRepository(reopened).get_log(entry.id) == updated
    assert len(repo.list(limit=1)) == 1
    assert repo.list(limit=1, offset=1)[0].id == first.id
    assert repo.get(999) is None
    with pytest.raises(NotFoundError):
        repo.save(GroupCounselingInput(name='없는 집단'), 999)


async def invoke(function, *args, **kwargs):
    return function(*args, **kwargs)


def test_group_status_reinitialize_and_calendar_filter(tmp_path):
    from datetime import timedelta
    from pydantic import ValidationError
    from maeumnarae.repositories.calendar_repo import CalendarRepository
    db = Database('test-groups', tmp_path / 'status.db')
    db.initialize()
    repo = GroupCounselingRepository(db)
    group = repo.save(GroupCounselingInput(name='집단'))
    start = datetime(2026, 10, 23, 9, tzinfo=timezone(timedelta(hours=9)))
    value = GroupLogInput(group_id=group.id, title='회기', starts_at=start, content_html='<p>기록</p>')
    log = repo.save_log(value)
    assert log.status == 'scheduled'
    db.initialize()
    db.initialize()
    restored = repo.get_log(log.id)
    assert restored.status == 'scheduled'
    assert restored.model_dump(exclude={'status'}) == log.model_dump(exclude={'status'})
    calendars = CalendarRepository(db)
    calendar = next(c for c in calendars.list() if c.source == 'counseling')
    for status in ('scheduled', 'completed', 'cancelled'):
        repo.save_log(value.model_copy(update={'status': status}), log.id)
        assert repo.list_logs(group.id)[0].status == status
        assert calendars.events(start.date(), start.date(), [calendar.id], status)[0].status == status
        other = 'completed' if status != 'completed' else 'scheduled'
        assert calendars.events(start.date(), start.date(), [calendar.id], other) == []
    with pytest.raises(ValidationError):
        GroupLogInput(group_id=group.id, title='회기', starts_at=start, status='invalid')


def test_group_editor_saves_selected_status():
    import inspect
    from maeumnarae.core.models import GroupLog

    async def check():
        now = datetime.now(timezone.utc)
        group = GroupCounseling(id=1, name='집단', created_at=now, updated_at=now)
        log = GroupLog(id=1, group_id=1, title='회기', starts_at=now,
                       status='completed', created_at=now, updated_at=now)
        repo = Mock()
        repo.get_log.return_value = log
        with Client(page('/group-status-editor')), patch('maeumnarae.views.group_counseling_view.run.io_bound', side_effect=invoke):
            view = GroupCounselingView(repo)
            view.selected = group

            async def interact(dialog):
                status = next(e for e in dialog.descendants() if isinstance(e, ui.select) and e.props.get('label') == '상담 상태')
                assert status.value == 'completed'
                status.value = 'cancelled'
                save = next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == '저장')
                handler = next(e.handler for e in save._event_listeners.values() if e.type == 'click')
                await inspect.getclosurevars(handler).nonlocals['callback']()
                return None

            with patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()):
                await view.open_editor(log=True, log_id=1)
            assert repo.save_log.call_args.args[0].status == 'cancelled'
            assert repo.save_log.call_args.args[1] == 1
    asyncio.run(check())


@pytest.mark.anyio
async def test_group_selection_and_stale_response():
    with Client(page('/group-test')):
        repo = Mock()
        now = datetime.now(timezone.utc)
        first = GroupCounseling(id=1, name='첫 집단', participants='참여자', created_at=now, updated_at=now)
        second = first.model_copy(update={'id': 2, 'name': '다음 집단'})
        repo.get.side_effect = lambda group_id: {1: first, 2: second}[group_id]
        repo.list_logs.return_value = []
        repo.count_logs.return_value = 0
        host = ui.column()
        view = GroupCounselingView(repo)
        view.students = Mock()
        view.students.list.return_value = []
        with host, patch('maeumnarae.views.group_counseling_view.ui.timer'):
            view.build()
        try:
            with patch('maeumnarae.views.group_counseling_view.run.io_bound', side_effect=invoke):
                await view.select_group(1)
            assert view.selected == first
            assert view.add_log.enabled
            assert '등록된 집단 상담 일지가 없습니다' in view.log_message.text
            repo.list_logs.assert_called_once_with(1, limit=10, offset=0)
            started, release = asyncio.Event(), asyncio.Event()

            async def delayed(function, *args, **kwargs):
                if function == repo.get and args == (1,):
                    started.set()
                    await release.wait()
                return function(*args, **kwargs)

            with patch('maeumnarae.views.group_counseling_view.run.io_bound', side_effect=delayed):
                task = asyncio.create_task(view.select_group(1))
                await started.wait()
                await view.select_group(2)
                release.set()
                await task
            assert view.selected == second
            texts = [element.text for element in view.details.descendants() if isinstance(element, ui.label)]
            assert '다음 집단' in texts
            assert '첫 집단' not in texts
        finally:
            host.delete()


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_group_and_log_editors_restore_fields():
    with Client(page('/group-test')):
        now = datetime.now(timezone.utc)
        group = GroupCounseling(id=1, name='집단', participants='참여자 목록', created_at=now, updated_at=now)
        repo = Mock()
        repo.list_logs.return_value = []
        repo.count_logs.return_value = 0
        host = ui.column()
        view = GroupCounselingView(repo)
        view.students = Mock()
        view.students.list.return_value = []
        with host, patch('maeumnarae.views.group_counseling_view.ui.timer'):
            view.build()
        view.selected = group
        seen = []

        async def inspect_dialog(dialog):
            seen.append(list(dialog.descendants()))
            return None

        def await_dialog(dialog):
            return inspect_dialog(dialog).__await__()

        try:
            with patch.object(ui.dialog, '__await__', await_dialog), patch('maeumnarae.views.group_counseling_view.run.io_bound', side_effect=invoke):
                await view.open_editor(edit_group=True)
                await view.open_editor(log=True)
            inputs = [element for element in seen[0] if isinstance(element, ui.input)]
            assert any(element.value == '집단' for element in inputs)
            assert any(element.value == '참여자 목록' for element in seen[0] if isinstance(element, ui.textarea))
            assert any(isinstance(element, ui.editor) for element in seen[1])
            assert not view.editor_open
        finally:
            host.delete()


def test_sidebar_group_page_order_and_reuse():
    from maeumnarae.views.app_layout import AppLayout

    with Client(page('/group-layout-test')):
        header = ui.header()
        drawer = ui.left_drawer()
        content = ui.column()
        layout = AppLayout(Mock(), Mock(), Mock())
        with patch('maeumnarae.views.group_counseling_view.ui.timer'), \
                patch('maeumnarae.views.auto_lock.ui.run_javascript'), \
                patch('maeumnarae.repositories.legacy_import_repo.LegacyImportRepository.load_period_times', return_value={}):
            layout.build(content, drawer, header)
            assert list(layout.buttons) == [
                'home', 'students', 'groups',
                'education_events', 'special_education', 'consultation', 'calendar',
                'statistics', 'settings']
            layout.navigate('groups')
            view = layout.group_view
            assert layout.panels['groups'].visible
            layout.navigate('home')
            assert not layout.panels['groups'].visible
            layout.navigate('groups')
            assert layout.group_view is view
            layout.navigate('consultation')
            consultation = layout.consultation_view
            assert layout.panels['consultation'].visible
            assert consultation.table.rows == []
            layout.navigate('home')
            layout.navigate('consultation')
            assert layout.consultation_view is consultation


def test_membership_and_combined_timeline(tmp_path):
    from datetime import timedelta
    from maeumnarae.core.models import CounselingInput, StudentInput
    from maeumnarae.repositories.counseling_repo import CounselingRepository
    from maeumnarae.repositories.student_repo import StudentRepository

    db = Database('test-members', tmp_path / 'members.db')
    db.initialize()
    students = StudentRepository(db)
    first = students.create(StudentInput(name='같은 이름', grade=1, classroom='1'))
    second = students.create(StudentInput(name='같은 이름', grade=2, classroom='2'))
    groups, counseling = GroupCounselingRepository(db), CounselingRepository(db)
    group = groups.save(GroupCounselingInput(name='연결 집단', participants='이전 메모', student_ids=[first.id, first.id]))
    assert group.student_ids == [first.id]
    assert '1학년 1반' in group.participant_labels[0]
    now = datetime.now(timezone.utc)
    individual = counseling.create(CounselingInput(student_id=first.id, title='개인', starts_at=now))
    earlier = groups.save_log(GroupLogInput(group_id=group.id, title='이전 집단 일지', starts_at=now - timedelta(days=1)))
    latest = groups.save_log(GroupLogInput(group_id=group.id, title='최근 집단 일지', starts_at=now + timedelta(days=1)))
    timeline = counseling.list_timeline(student_id=first.id)
    assert [(item.kind, item.id) for item in timeline] == [('group', latest.id), ('individual', individual.id), ('group', earlier.id)]
    assert timeline[0].group_name == '연결 집단'
    assert not hasattr(timeline[0], 'content_html')
    assert counseling.list_timeline(student_id=second.id) == []
    assert counseling.list_timeline(student_id=first.id, limit=1, offset=1) == [timeline[1]]
    with pytest.raises(ConflictError):
        groups.save(GroupCounselingInput(name='잘못된 변경', student_ids=[999]), group.id)
    assert groups.get(group.id) == group  # 잘못된 학생 연결은 전체 변경을 롤백한다.
    groups.save(GroupCounselingInput(name='연결 집단', participants='이전 메모', student_ids=[second.id]), group.id)
    assert [item.kind for item in counseling.list_timeline(student_id=first.id)] == ['individual']
    assert len(counseling.list_timeline(student_id=second.id)) == 2
    db.initialize()
    assert groups.get(group.id).student_ids == [second.id]
    assert groups.get(group.id).participants == '이전 메모'


def test_reinitialize_preserves_group_participant_text(tmp_path):
    db = Database('migration-members', tmp_path / 'legacy-groups.db')
    db.initialize()
    repo = GroupCounselingRepository(db)
    group = repo.save(GroupCounselingInput(name='기존 집단', participants='이름만 적어 둔 참여자'))
    db.initialize()
    db.initialize()
    restored = repo.get(group.id)
    assert restored.participants == group.participants
    assert restored.student_ids == []


def test_group_period_and_area_round_trip(tmp_path):
    db = Database('test-period', tmp_path / 'period.db')
    db.initialize()
    repo = GroupCounselingRepository(db)
    group = repo.save(GroupCounselingInput(name='운영 집단', period='2026-10-19 - 2026-11-30', counseling_area='진로'))
    assert repo.get(group.id).period == '2026-10-19 - 2026-11-30'
    assert repo.list()[0].counseling_area == '진로'
    changed = repo.save(GroupCounselingInput(name='운영 집단', period='2026-10-20', counseling_area='학업'), group.id)
    assert changed.period == '2026-10-20'
    assert changed.created_at == group.created_at
    reopened = Database('test-period', db.path)
    reopened.initialize()
    assert GroupCounselingRepository(reopened).get(group.id) == changed
    for period in ('2026-11-30 - 2026-10-19', '2026-02-30', '2026-10-19 - ', '잘못된 날짜'):
        with pytest.raises(ValueError):
            GroupCounselingInput(name='집단', period=period)
    cleared = repo.save(GroupCounselingInput(name='운영 집단'), group.id)
    assert cleared.period == cleared.counseling_area == ''


def test_group_fields_survive_reinitialize(tmp_path):
    db = Database('test-v9', tmp_path / 'v9.db')
    db.initialize()
    repo = GroupCounselingRepository(db)
    old = repo.save(GroupCounselingInput(name='기존 집단', purpose='기존 목표'))
    db.initialize()
    db.initialize()
    assert repo.get(old.id) == old


@pytest.mark.anyio
async def test_group_editor_saves_period_and_area():
    import inspect
    from unittest.mock import AsyncMock

    with Client(page('/group-fields-test')):
        now = datetime.now(timezone.utc)
        group = GroupCounseling(id=1, name='집단', period='2026-10-19 - 2026-11-30',
                                counseling_area='진로', created_at=now, updated_at=now)
        repo = Mock()
        repo.save.return_value = group
        view = GroupCounselingView(repo)
        view.students = Mock()
        view.students.list.return_value = []
        view.selected = group
        view.load_groups = AsyncMock()
        view.select_group = AsyncMock()

        async def interact(dialog):
            elements = list(dialog.descendants())
            period = next(element for element in elements if isinstance(element, ui.date_input))
            area = next(element for element in elements if isinstance(element, ui.select) and element.label == '상담 영역')
            assert period.value == group.period
            assert area.value == '진로'
            save_button = next(element for element in elements if isinstance(element, ui.button) and element.text == '저장')
            handler = next(listener.handler for listener in save_button._event_listeners.values() if listener.type == 'click')
            save = inspect.getclosurevars(handler).nonlocals['callback']
            period.value = ''
            await save()
            repo.save.assert_not_called()
            assert not dialog.submitted.is_set()
            period.value = '2026-11-30 - 2026-10-19'
            await save()
            repo.save.assert_not_called()
            assert not dialog.submitted.is_set()
            period.picker.value = {'from': '2026-10-20', 'to': '2026-11-20'}
            area.value = '학업'
            await save()
            assert dialog.submitted.is_set()
            return dialog._result

        with patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()), \
                patch('maeumnarae.views.group_counseling_view.run.io_bound', side_effect=invoke), \
                patch('maeumnarae.views.group_counseling_view.ui.notify'):
            await view.open_editor(edit_group=True)
        value, group_id = repo.save.call_args.args
        assert value.period == '2026-10-20 - 2026-11-20'
        assert value.counseling_area == '학업'
        assert group_id == group.id
        assert not view.editor_open


@pytest.mark.anyio
@pytest.mark.parametrize('period,school_year', [
    ('2026-03-01 - 2027-02-28', 2026),
    ('2027-02-28', 2026),
    ('2027-03-01', 2027),
    ('2026-12-01 - 2027-04-30', 2026),
    ('', None),
])
async def test_group_list_school_year_from_start_date(period, school_year):
    now = datetime.now(timezone.utc)
    group = GroupCounseling(id=1, name='집단', period=period, created_at=now, updated_at=now)
    assert group.school_year == school_year
    repo = Mock()
    repo.list.return_value = [group]
    with Client(page('/group-school-year-test')), patch('maeumnarae.views.group_counseling_view.ui.timer'), \
            patch('maeumnarae.views.group_counseling_view.run.io_bound', side_effect=invoke):
        view = GroupCounselingView(repo)
        view.build()
        await view.load_groups()
        assert view.table.rows[0]['school_year'] == (school_year if school_year is not None else '미입력')
        assert view.table.columns[0]['label'] == '학년도'


def test_attendance_round_trip_and_membership_changes(tmp_path):
    from maeumnarae.core.models import StudentInput
    from maeumnarae.repositories.student_repo import StudentRepository

    db = Database('attendance', tmp_path / 'attendance.db')
    db.initialize()
    students = StudentRepository(db)
    first = students.create(StudentInput(name='동명이인', grade=1, classroom='1'))
    second = students.create(StudentInput(name='동명이인', grade=2, classroom='1'))
    repo = GroupCounselingRepository(db)
    group = repo.save(GroupCounselingInput(name='집단', student_ids=[first.id, second.id]))
    value = GroupLogInput(group_id=group.id, title='출석 기록', starts_at=datetime.now(timezone.utc),
                          attendance=[dict(student_id=first.id, name=group.participant_labels[0],
                                           attended=True, attitude='활동에 적극적으로 참여함'),
                                      dict(student_id=second.id, name=group.participant_labels[1],
                                           attended=False, attitude='결석')])
    entry = repo.save_log(value)
    repo.save(GroupCounselingInput(name='집단', student_ids=[second.id]), group.id)
    db.initialize()
    assert repo.get_log(entry.id).attendance == value.attendance
    assert repo.list_logs(group.id)[0].attendance == value.attendance
    changed = value.model_dump()
    changed['attendance'][0].update(attended=False, attitude='수정')
    repo.save_log(GroupLogInput(**changed), entry.id)
    assert repo.get_log(entry.id).attendance[0].attitude == '수정'
    assert not repo.get_log(entry.id).attendance[0].attended
    another = repo.save_log(GroupLogInput(group_id=group.id, title='다음 회기', starts_at=value.starts_at))
    assert another.attendance == []


def test_existing_database_adds_attendance_without_losing_log(tmp_path):
    db = Database('attendance', tmp_path / 'old-attendance.db')
    db.initialize()
    repo = GroupCounselingRepository(db)
    group = repo.save(GroupCounselingInput(name='기존 집단'))
    entry = repo.save_log(GroupLogInput(group_id=group.id, title='기존 일지',
                                      starts_at=datetime.now(timezone.utc), content_html='<p>기존 내용</p>'))
    with db.session(write=True) as connection:
        connection.execute('ALTER TABLE group_counseling_logs DROP COLUMN attendance')
    reopened = Database('attendance', db.path)
    reopened.initialize()
    reopened.initialize()
    assert GroupCounselingRepository(reopened).get_log(entry.id) == entry


@pytest.mark.anyio
@pytest.mark.parametrize('existing', [False, True])
async def test_attendance_table_edits_are_saved(existing):
    import inspect
    from types import SimpleNamespace
    from maeumnarae.core.models import GroupLog

    now = datetime.now(timezone.utc)
    group = GroupCounseling(id=1, name='집단', student_ids=[10, 20],
                            participant_labels=['학생 A · 1학년 1반', '학생 B · 2학년 1반'],
                            created_at=now, updated_at=now)
    log = GroupLog(id=1, group_id=1, title='회기', starts_at=now, created_at=now, updated_at=now,
                   attendance=[dict(student_id=30, name='이전 참여 학생', attended=True, attitude='기존 태도')])
    repo = Mock()
    repo.get_log.return_value = log
    with Client(page('/attendance-editor')), patch(
            'maeumnarae.views.group_counseling_view.run.io_bound', side_effect=invoke):
        view = GroupCounselingView(repo)
        view.selected = group

        async def interact(dialog):
            table = next(e for e in dialog.descendants() if isinstance(e, ui.table))
            assert [c['label'] for c in table.columns] == ['이름', '출석', '참여 태도']
            assert table.row_key == 'student_id'
            if existing:
                assert table.rows == [row.model_dump() for row in log.attendance]
            else:
                assert [row['student_id'] for row in table.rows] == [10, 20]
                assert not any(row['attended'] for row in table.rows)
                title = next(e for e in dialog.descendants() if isinstance(e, ui.input) and e.label == '일지 제목')
                title.value = '새 회기'
            change = next(e.handler for e in table._event_listeners.values() if e.type == 'attendance_change')
            student_id = table.rows[0]['student_id']
            change(SimpleNamespace(args=dict(student_id=student_id, field='attended', value=True)))
            change(SimpleNamespace(args=dict(student_id=student_id, field='attitude', value='표에서 입력한 태도')))
            save = next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == '저장')
            handler = next(e.handler for e in save._event_listeners.values() if e.type == 'click')
            await inspect.getclosurevars(handler).nonlocals['callback']()
            return None

        with patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()):
            await view.open_editor(log=True, log_id=1 if existing else None)
        value = repo.save_log.call_args.args[0]
        assert value.attendance[0].attended
        assert value.attendance[0].attitude == '표에서 입력한 태도'
        assert value.attendance[0].student_id == (30 if existing else 10)
