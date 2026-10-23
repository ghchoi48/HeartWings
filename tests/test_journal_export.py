"""업로드 서식, 전체 일지 조회, 한국 학년도 경계와 비공개 내용 제외 검증."""
import asyncio
from datetime import date, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import warnings
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from nicegui import Client, ui
from nicegui.page import page
from openpyxl import load_workbook

from database import Database, DatabaseError
from models import (StudentInput, StudentEnrollmentInput, TeacherInput, CounselingInput,
                    GroupCounselingInput, GroupLogInput, SpecialEducationInput, ConsultationInput,
                    PsychologicalTestInput, EducationEventInput)
from reporting import KST
from repositories.student_repo import StudentRepository
from repositories.teacher_repo import TeacherRepository
from repositories.counseling_repo import CounselingRepository
from repositories.group_counseling_repo import GroupCounselingRepository
from repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from repositories.consultation_repo import ConsultationRepository
from repositories.psychological_test_repo import PsychologicalTestRepository
from repositories.education_event_repo import EducationEventRepository
from repositories.journal_export_repo import JournalExportRepository, JournalSnapshot
from services.journal_export import (ExportOptions, ExportResult, TEMPLATE, export_journals,
                                     export_rows, school_year, workbook_bytes)
from views.journal_export_view import JournalExportView


def read_workbook(content):
    # openpyxl는 읽기 검증용이다. 재저장하지 않아 x14 검사를 보존한다.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Data Validation extension is not supported')
        return load_workbook(BytesIO(content))


@pytest.mark.parametrize('day, expected', [
    ('2024-02-29', 2023), ('2024-03-01', 2024), ('2026-02-28', 2025),
    ('2026-03-01', 2026), ('2026-12-31', 2026), ('2027-01-01', 2026), ('2027-02-28', 2026),
])
def test_school_year(day, expected):
    assert school_year(date.fromisoformat(day)) == expected


def test_all_record_types_export_without_private_text(tmp_path):
    db = Database('test-export', tmp_path / 'journals.db')
    db.initialize()
    students = StudentRepository(db)
    student = students.create(StudentInput(name='절대포함금지학생', school_year=2026, grade=3, classroom='1', gender='남'))
    students.save_enrollment(student.id, StudentEnrollmentInput(school_year=2025, grade=2, classroom='1'))
    second = students.create(StudentInput(name='절대포함금지학생2', school_year=2026, grade=4, classroom='1', gender='여'))
    individual = CounselingRepository(db)
    individual.create(CounselingInput(student_id=student.id, title='절대포함금지제목',
        content_markdown='절대포함금지본문', private_note_html='절대포함금지메모',
        starts_at=datetime(2026, 2, 28, 23, 59, tzinfo=KST), duration_minutes=80,
        counseling_area='진로', status='cancelled', counseling_method='전화', counseling_target='학생본인'))
    special = SpecialEducationRepository(db).save(SpecialEducationInput(student_id=student.id, title='교육', law='교원지위법'))
    SpecialEducationLogRepository(db).create(CounselingInput(student_id=student.id, case_id=special.id,
        title='절대포함금지교육제목', starts_at=datetime(2026, 3, 1, 0, tzinfo=KST), counseling_area='학교폭력 가해'))
    groups = GroupCounselingRepository(db)
    group = groups.save(GroupCounselingInput(name='집단', student_ids=[student.id, second.id], counseling_area='학업'))
    groups.save_log(GroupLogInput(group_id=group.id, title='절대포함금지집단제목',
        starts_at=datetime(2026, 3, 1, 10, tzinfo=KST), duration_minutes=125, status='completed'))
    teacher = TeacherRepository(db).save(TeacherInput(name='절대포함금지교사'))
    ConsultationRepository(db).save(ConsultationInput(teacher_id=teacher.id, title='절대포함금지자문제목',
        starts_at=datetime(2026, 3, 1, 11, tzinfo=KST), consultation_area='정서발달'))
    PsychologicalTestRepository(db).save(PsychologicalTestInput(student_id=student.id,
        title='절대포함금지검사제목', test_date=date(2026, 3, 1), test_time='12:00', duration_minutes=40))
    EducationEventRepository(db).save(EducationEventInput(title='절대포함금지행사제목', event_date=date(2026, 3, 1)))
    EducationEventRepository(db).save(EducationEventInput(title='절대포함금지단체검사제목',
        category='단체심리검사', event_date=date(2026, 3, 1), duration_minutes=60, participant_count=128))

    snapshot = JournalExportRepository(db).snapshot()
    assert '절대포함금지' not in repr(snapshot)
    result = export_journals(db, ExportOptions())
    assert result.count == 7
    assert result.counts == {'개인상담': 1, '특별교육': 1, '교육/행사': 2, '집단상담': 1, '자문': 1, '심리검사': 1}
    book = read_workbook(result.content)
    sheet = book['입력']
    assert book.sheetnames == ['입력', '참조'] and book['참조'].sheet_state == 'hidden'
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    assert len(rows) == 7
    for row in rows:
        assert len(row) == 16
        assert row[0] == '전문상담' and row[14] == '전문상담교사'
        assert row[4] == row[10] == row[11]
    assert rows[0][6:10] == (2025, '20260228', None, None)
    assert rows[0][12:14] == (1, 20) and rows[0][15] == '전화'
    special_row = next(row for row in rows if row[4] == '학교폭력 가해')
    assert special_row[2:5] == ('상담', '개인상담', '학교폭력 가해')
    assert special_row[6:10] == (2026, '20260301', None, None)
    group_row = next(row for row in rows if row[3] == '집단상담')
    assert group_row[5] == 2 and group_row[8:10] == (None, None)
    assert group_row[12:14] == (2, 5)
    assert any(row[2:5] == ('검사', '심리검사', '집단심리검사') for row in rows)
    assert any(row[2:5] == ('검사', '심리검사', '개인심리검사') for row in rows)
    assert next(row for row in rows if row[4] == '집단심리검사')[5] == 128
    assert all(row[8:10] == (None, None) for row in rows)
    assert all(row[15] == '면담' for row in rows[1:])
    assert any('상담인원 확인 필요' in issue for issue in result.issues)
    assert any('상담시간 확인 필요' in issue for issue in result.issues)
    with ZipFile(BytesIO(result.content)) as archive:
        assert all('절대포함금지'.encode() not in archive.read(name) for name in archive.namelist())
    filtered, _, _ = export_rows(snapshot, ExportOptions(start=date(2026, 3, 1), end=date(2026, 3, 1), status='completed'))
    assert len(filtered) == 5  # 예약 특별교육과 취소 개인상담 제외, 상태 없는 검사·교육 포함


def test_template_preserved_validation_extended_and_strings_are_not_formulas():
    row = ('전문상담', 'Wee클래스', '상담', '개인상담', '기타', 1, 2026, '20261023',
           '1학년', '남', '=1+1', '<메모>&', 0, 50, '전문상담교사', '면담')
    content = workbook_bytes([row] * 3200)
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'x14': 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main',
          'xm': 'http://schemas.microsoft.com/office/excel/2006/main'}
    with ZipFile(TEMPLATE) as original, ZipFile(BytesIO(content)) as saved:
        assert original.namelist() == saved.namelist()
        for name in original.namelist():
            if name != 'xl/worksheets/sheet1.xml':
                assert original.read(name) == saved.read(name)
        tree = ET.fromstring(saved.read('xl/worksheets/sheet1.xml'))
        assert tree.find('s:dimension', ns).attrib['ref'] == 'A1:P3201'
        assert len(tree.findall('s:sheetData/s:row', ns)) == 3201
        validations = tree.find('s:dataValidations', ns)
        assert validations.attrib['count'] == '3'
        assert [(item.attrib['sqref'], item.find('s:formula1', ns).text) for item in validations] == [
            ('C2:C3201', 'INDIRECT(A2)'), ('D2:D3201', 'INDIRECT(C2)'), ('E2:E3201', 'INDIRECT(D2)')]
        extended = tree.findall('.//x14:dataValidation/xm:sqref', ns)
        assert len(extended) == 6 and all(item.text.endswith('3201') for item in extended)
    sheet = read_workbook(content)['입력']
    assert sheet['K2'].value == '=1+1' and sheet['K2'].data_type == 's'
    assert sheet['L2'].value == '<메모>&'
    assert sheet['M2'].value == 0 and sheet['M2'].data_type == 'n'
    empty = read_workbook(workbook_bytes([]))['입력']
    assert empty.max_row == 1 and empty.max_column == 16


def test_missing_demographics_are_not_guessed_and_all_rows_are_kept():
    record = dict(kind='individual', id=1, student_id=1, starts_at='2026-02-28T15:00:00+00:00',
                  duration_minutes=30, area='', target='', method='', status='scheduled')
    snapshot = JournalSnapshot(tuple(dict(record, id=i) for i in range(1001)), {})
    rows, issues, _ = export_rows(snapshot, ExportOptions(wee_class='일반'))
    assert len(rows) == 1001 and len(issues) == 1001
    assert rows[0][6:10] == (2026, '20260301', '', '')  # 한국 시각으로 3월 1일
    assert rows[0][1] == '일반' and rows[0][15] == ''
    assert rows[0][4] == ''
    with pytest.raises(ValueError):
        export_rows(snapshot, ExportOptions(start=date(2026, 3, 2), end=date(2026, 3, 1)))


def test_export_view_download_and_invalidate():
    async def check():
        with Client(page('/journal-export-test')):
            view = JournalExportView(Mock())
            view.build()
            result = ExportResult(b'xlsx-test', 1, {'개인상담': 1}, ('엑셀 2행 확인 필요',))
            with patch('views.journal_export_view.run.io_bound', new_callable=AsyncMock, return_value=result) as io:
                await view.generate()
                assert view.download_button.enabled
                assert io.await_args.args[2] == ExportOptions()
                with patch('views.journal_export_view.ui.download.content') as download:
                    view.download()
                    assert download.call_args.args[0] == b'xlsx-test'
                    view.invalidate()
                    view.download()
                    download.assert_called_once()
                assert not view.download_button.enabled
            with patch('views.journal_export_view.run.io_bound', new_callable=AsyncMock, side_effect=DatabaseError('DB 오류')):
                await view.generate()
                assert view.result is None and not view.busy
                assert view.prepare.enabled and not view.download_button.enabled
                assert 'DB 오류' in view.message.text
    asyncio.run(check())


@pytest.mark.parametrize('kind', ['individual', 'special', 'group', 'consultation', 'test', 'education'])
def test_media_only_uses_individual_record_and_demographics_are_blank(kind):
    record = dict(kind=kind, id=1, student_id=1, group_id=1, category='교육',
                  starts_at='2026-10-23T09:00:00+09:00', duration_minutes=30,
                  area='진로', target='학생본인', method='사이버상담', participant_count=0)
    rows, _, _ = export_rows(JournalSnapshot((record,), {1: (1, 2)}), ExportOptions())
    assert rows[0][15] == ('사이버상담' if kind == 'individual' else '면담')
    assert rows[0][8:10] == ('', '')
    if kind == 'education':
        assert rows[0][5] == 0


@pytest.mark.parametrize('kind,target,area,middle', [
    ('individual', '학생본인', '진로', '개인상담'),
    ('individual', '학생본인', '기존 상담분야', '개인상담'),
    ('individual', '보호자(가족)', '학업', '학부모상담'),
    ('consultation', '', '정서발달', '교원자문'),
    ('consultation', '', '', '교원자문'),
])
def test_saved_area_is_exported_to_counseling_category(kind, target, area, middle):
    record = dict(kind=kind, id=1, starts_at='2026-10-23T09:00:00+09:00',
                  duration_minutes=30, area=area, target=target, method='면담')
    rows, issues, _ = export_rows(JournalSnapshot((record,), {}), ExportOptions())
    sheet = read_workbook(workbook_bytes(rows))['입력']
    assert sheet['E1'].value == '*상담구분'
    assert sheet['D2'].value == middle
    assert sheet['E2'].value == (area or None)
    assert sheet['K2'].value == sheet['L2'].value == sheet['E2'].value
    if area in ('기존 상담분야', '학업', ''):
        assert any('저장된 값 유지' in issue for issue in issues)
