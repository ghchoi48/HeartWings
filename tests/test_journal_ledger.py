"""상담 대장과 학생 연결 파일, 기존 NEIS 서식 호환성 검증."""
import asyncio
from datetime import date, datetime
from io import BytesIO
from unittest.mock import AsyncMock, Mock, patch

from nicegui import Client, ui
from nicegui.page import page
from openpyxl import load_workbook

from maeumnarae.core.database import Database
from maeumnarae.core.models import StudentInput, StudentEnrollmentInput, CounselingInput, GroupCounselingInput, GroupLogInput
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.repositories.counseling_repo import CounselingRepository
from maeumnarae.repositories.group_counseling_repo import GroupCounselingRepository
from maeumnarae.repositories.journal_export_repo import JournalSnapshot
from maeumnarae.services.journal_export import ExportOptions, LedgerExportResult, export_ledger, export_rows, export_journals
from maeumnarae.services.reporting import KST
from maeumnarae.views.journal_export_view import JournalExportView


def test_ledger_filters_ids_and_linked_students(tmp_path):
    db = Database('ledger-test', tmp_path / 'ledger.db')
    db.initialize()
    students = StudentRepository(db)
    first = students.create(StudentInput(name='=1+1', school_year=2025, grade=1, classroom='1', gender='남'))
    second = students.create(StudentInput(name='동명이인', school_year=2026, grade=2, classroom='02', student_number='007'))
    students.create(StudentInput(name='미연결학생', grade=3, classroom='1'))
    students.save_enrollment(first.id, StudentEnrollmentInput(school_year=2026, grade=2, classroom='3', student_number='05'))
    logs = CounselingRepository(db)
    for day, status in [(1, 'completed'), (2, 'completed'), (3, 'cancelled')]:
        logs.create(CounselingInput(student_id=first.id, starts_at=datetime(2026, 5, day, 10, tzinfo=KST),
                                   title='비공개제목', content_markdown='비공개본문', status=status))
    groups = GroupCounselingRepository(db)
    group = groups.save(GroupCounselingInput(name='집단', student_ids=[first.id, second.id]))
    groups.save_log(GroupLogInput(group_id=group.id, title='집단회기', starts_at=datetime(2026, 5, 2, 11, tzinfo=KST), status='completed'))
    options = ExportOptions(start=date(2026, 5, 2), end=date(2026, 5, 3), status='completed')
    result = export_ledger(db, options)
    sheet = load_workbook(BytesIO(result.content)).active
    rows = list(sheet.values)
    assert sheet.max_column == 17 and result.count == 2
    assert rows[0][7:11] == ('상담일자', '학생 ID', '학년', '성별')
    assert rows[1][8] == first.id
    assert rows[2][8] == f'{first.id}, {second.id}'
    assert '비공개' not in str(rows)
    roster = load_workbook(BytesIO(result.students_content)).active
    assert list(roster.values) == [('학생 ID', '학년', '반', '번호', '성별', '이름'),
                                 (first.id, 2, '3', '05', '남', '=1+1'),
                                 (second.id, 2, '02', '007', None, '동명이인')]
    assert roster['F2'].data_type == 's'
    assert result.student_count == 2
    assert roster.freeze_panes == 'A2' and roster.auto_filter.ref == 'A1:F3'
    # 기간을 좁히면 집단에만 연결된 학생은 학생 파일에서도 제외된다.
    single = export_ledger(db, ExportOptions(start=date(2026, 5, 1), end=date(2026, 5, 1)))
    assert single.student_count == 1
    empty = export_ledger(db, ExportOptions(start=date(2020, 1, 1), end=date(2020, 1, 1)))
    assert empty.count == empty.student_count == 0
    assert load_workbook(BytesIO(empty.students_content)).active.max_row == 1
    neis = load_workbook(BytesIO(export_journals(db, options).content), read_only=True)
    assert neis['입력'].max_column == 16


def test_student_ids_for_all_record_kinds():
    base = dict(id=1, student_id=42, group_id=1, starts_at='2026-05-01T10:00:00+09:00',
                duration_minutes=50, category='교육', participant_count=10)
    for kind, expected in [('individual', 42), ('special', 42), ('test', 42),
                           ('group', '42, 43'), ('consultation', ''), ('education', '')]:
        snapshot = JournalSnapshot((dict(base, kind=kind),), {1: (42, 43)})
        original, _, _ = export_rows(snapshot, ExportOptions())
        ledger, _, _ = export_rows(snapshot, ExportOptions(), include_student_ids=True)
        assert ledger[0] == original[0][:8] + (expected,) + original[0][8:]


def test_ledger_view_two_downloads_and_invalidation():
    async def check():
        with Client(page('/ledger-export-test')):
            view = JournalExportView(Mock(), ledger=True)
            view.build()
            result = LedgerExportResult(b'ledger', 1, {}, (), b'students', 1)
            with patch('maeumnarae.views.journal_export_view.run.io_bound', new_callable=AsyncMock, return_value=result) as io:
                await view.generate()
                assert io.await_args.args[0] is export_ledger
                assert view.download_button.enabled and view.students_download_button.enabled
                with patch('maeumnarae.views.journal_export_view.ui.download.content') as download:
                    view.download()
                    view.download_students()
                    assert [call.args[0] for call in download.call_args_list] == [b'ledger', b'students']
                    assert download.call_args_list[0].args[1].startswith('상담대장_')
                    view.invalidate()
                    view.download_students()
                    assert download.call_count == 2
                assert not view.download_button.enabled and not view.students_download_button.enabled
    asyncio.run(check())
