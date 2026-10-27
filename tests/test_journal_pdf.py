"""실제 암호화 DB의 여섯 종류 조회, 학년도 경계와 PDF 내용 검증."""
import asyncio
from dataclasses import replace
from datetime import date, datetime
from io import BytesIO
from unittest.mock import patch

import pytest
from pypdf import PdfReader
from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.core.models import (StudentInput, CounselingInput, GroupCounselingInput, GroupLogInput,
    GroupAttendanceInput, TeacherInput, ConsultationInput, SpecialEducationInput, PsychologicalTestInput, EducationEventInput)
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.repositories.counseling_repo import CounselingRepository
from maeumnarae.repositories.group_counseling_repo import GroupCounselingRepository
from maeumnarae.repositories.teacher_repo import TeacherRepository
from maeumnarae.repositories.consultation_repo import ConsultationRepository
from maeumnarae.repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from maeumnarae.repositories.psychological_test_repo import PsychologicalTestRepository
from maeumnarae.repositories.education_event_repo import EducationEventRepository
from maeumnarae.repositories.journal_print_repo import JournalPrintRepository
from maeumnarae.services.journal_print_models import PrintRequest, PrintRecord, PrintSnapshot, KINDS
from maeumnarae.services.journal_pdf import build_pdf, masked_snapshot
from maeumnarae.services.reporting import KST


@pytest.fixture
def records(tmp_path):
    db = Database('pdf-test-only', tmp_path / 'pdf.db')
    db.initialize()
    students = StudentRepository(db)
    student = students.create(StudentInput(name='동명이인', grade=1, classroom='1'))
    other = students.create(StudentInput(name='동명이인', grade=2, classroom='2'))
    counseling = CounselingRepository(db)
    for owner, moment, status in [(student, '2026-02-28T14:59:59+00:00', 'completed'),
                                  (student, '2026-02-28T15:00:00+00:00', 'completed'),
                                  (student, '2027-02-28T14:59:59.999999+00:00', 'completed'),
                                  (student, '2027-02-28T15:00:00+00:00', 'completed'),
                                  (other, '2026-06-01T00:00:00+09:00', 'completed'),
                                  (other, '2026-06-02T00:00:00+09:00', 'scheduled'),
                                  (other, '2026-06-03T00:00:00+09:00', 'cancelled')]:
        counseling.create(CounselingInput(student_id=owner.id, title='상담', starts_at=datetime.fromisoformat(moment),
            status=status, content_markdown='상담 본문', private_note_html='출력금지비밀메모'))
    moment = datetime(2026, 5, 1, 9, tzinfo=KST)
    group_repo = GroupCounselingRepository(db)
    group = group_repo.save(GroupCounselingInput(name='친구 관계', student_ids=[student.id]))
    group_repo.save_log(GroupLogInput(group_id=group.id, starts_at=moment, title='집단 회기', status='completed',
        attendance=[GroupAttendanceInput(student_id=student.id, name='회기 당시 이름', attended=True, attitude='적극적')]))
    teacher = TeacherRepository(db).save(TeacherInput(name='교사실명'))
    ConsultationRepository(db).save(ConsultationInput(teacher_id=teacher.id, starts_at=moment, title='교원 자문'))
    special = SpecialEducationRepository(db).save(SpecialEducationInput(student_id=student.id, title='특별교육', law='교원지위법'))
    SpecialEducationLogRepository(db).create(CounselingInput(student_id=student.id, case_id=special.id,
        starts_at=moment, title='교육 회기', status='completed'))
    PsychologicalTestRepository(db).save(PsychologicalTestInput(student_id=student.id, title='검사', test_date=moment.date()))
    EducationEventRepository(db).save(EducationEventInput(title='행사', event_date=moment.date(), participant_count=0))
    return db


def test_all_kinds_year_boundary_status_identity_and_private(records):
    repo = JournalPrintRepository(records)
    snapshot = repo.snapshot(PrintRequest(school_year=2026))
    assert snapshot.counts == dict(individual=3, group=1, special=1, consultation=1, test=1, education=1)
    assert [r.id for r in snapshot.records if r.kind == 'individual'] == [2, 3, 5]
    assert '출력금지비밀메모' not in repr(snapshot)
    assert next(r for r in snapshot.records if r.kind == 'group').attendance[0]['name'] == '회기 당시 이름'
    all_status = repo.snapshot(PrintRequest(school_year=2026, statuses=('completed', 'scheduled', 'cancelled')))
    assert len(all_status.records) == 10
    assert len(repo.snapshot(PrintRequest(school_year=2026, statuses=())).records) == 2
    selected = repo.snapshot(PrintRequest(refs=(('individual', 6),)))
    assert selected.records[0].status == 'scheduled'
    with pytest.raises(DatabaseError):
        repo.snapshot(PrintRequest(refs=(('individual', 99999),)))
    masked = masked_snapshot(snapshot)
    individual = [r for r in masked.records if r.kind == 'individual']
    assert individual[0].subject == individual[1].subject != individual[2].subject
    assert next(r for r in masked.records if r.kind == 'group').attendance[0]['name'] == individual[0].subject
    assert '교사실명' not in repr(masked)
    content = build_pdf(snapshot, PrintRequest(school_year=2026, mask_names=True))
    reader = PdfReader(BytesIO(content))
    text = '\n'.join(p.extract_text() for p in reader.pages)
    assert '동명이인' not in text and '회기 당시 이름' not in text and '출력금지비밀메모' not in text
    assert all(label in text for label in KINDS.values())
    assert len(reader.pages) == len(snapshot.records) + 1
    assert len(reader.outline) >= 6
    records.lock()
    with pytest.raises(DatabaseError):
        repo.snapshot(PrintRequest(school_year=2026))


def sample_snapshot():
    html = '<p style="text-align:center"><b>한글 강조</b>와 일반 문장</p><ul><li>첫 항목</li><li>둘째 항목</li></ul>'
    html += '<script>출력금지스크립트</script><img src="https://invalid.example/a.png">'
    html += '<table><tr><th>항목</th><th>내용</th></tr><tr><td>목표</td><td>학교 적응과 정서 지원</td></tr></table>'
    html += '<p>긴 본문 한글 내용입니다. 문장이 다음 페이지까지 이어지는지 확인합니다.</p>' * 100
    r = PrintRecord('individual', 1, 'student', 1, '가상학생', datetime(2026, 5, 1, 9, tzinfo=KST),
                    '상담 일지 출력 검증', '상담교사', 'completed', 50, html, 'html')
    return PrintSnapshot('가상학교', (r,))


def test_long_korean_rich_pdf_and_leap_year(tmp_path):
    content = build_pdf(sample_snapshot(), PrintRequest(school_year=2023))
    reader = PdfReader(BytesIO(content))
    text = '\n'.join(p.extract_text() for p in reader.pages)
    assert '2024-02-29' in text
    assert '한글 강조' in text and '학교 적응과 정서 지원' in text
    assert '출력금지스크립트' not in text
    assert text.count('긴 본문 한글 내용입니다.') == 100
    assert len(reader.pages) > 3
    with pytest.raises(ValueError):
        build_pdf(PrintSnapshot('', ()), PrintRequest(school_year=2026))


def test_long_attendance_rows_split_without_losing_text():
    record = sample_snapshot().records[0]
    attendance = tuple(dict(student_id=i, name=f'참여자 {i}', attended=True,
                           attitude=('\n'.join(f'태도문장{n:04d}' for n in range(200)) if i == 1 else f'태도 {i}'))
                       for i in range(1, 61))
    record = replace(record, kind='group', subject_type='group', content='', attendance=attendance)
    content = build_pdf(PrintSnapshot('학교', (record,)), PrintRequest(refs=(('group', 1),)))
    reader = PdfReader(BytesIO(content))
    text = '\n'.join(p.extract_text() for p in reader.pages)
    assert '참여자 60' in text
    assert all(f'태도문장{n:04d}' in text for n in range(200))
    assert len(reader.pages) > 3


def test_selection_survives_pages_and_resets_scope():
    from maeumnarae.views.journal_print_view import PrintSelection, invalidate_prints, live
    with Client(page('/pdf-selection-test')) as client:
        selection = PrintSelection(None, 'individual')
        selection.set_scope((1, 1))
        selection.toolbar()
        selection.toggle(1, True)
        selection.set_scope((1, 1))
        assert selection.ids == {1}
        selection.set_scope((1, 2))
        assert selection.ids == set()
        epoch = getattr(client, '_journal_print_epoch', 0)
        invalidate_prints()
        assert not live(selection.button, epoch)


def test_print_ui_generates_and_blocks_after_navigation(records):
    from maeumnarae.views.journal_print_view import print_dialog, invalidate_prints
    from inspect import getclosurevars
    async def check():
        with Client(page('/pdf-ui-test')):
            anchor = ui.button('anchor')
            async def invoke(fn, *args, **kwargs):
                return fn(*args, **kwargs)
            with patch('maeumnarae.views.journal_print_view.live', return_value=True), \
                 patch('maeumnarae.views.journal_print_view.run.io_bound', side_effect=invoke), \
                 patch('maeumnarae.views.journal_print_view.ui.timer'), \
                 patch('maeumnarae.views.journal_print_view.ui.download.content') as download:
                await print_dialog(records, PrintRequest(school_year=2026), anchor)
                button = next(e for e in anchor.client.elements.values() if isinstance(e, ui.button) and e.text == 'PDF 생성 및 다운로드')
                listener = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
                handler = getclosurevars(listener).nonlocals['callback']
                await handler()
                assert download.call_args.args[0].startswith(b'%PDF-')
                assert download.call_args.args[1] == '마음나래_2026학년도_전체일지.pdf'
                with patch('maeumnarae.views.journal_print_view.live', return_value=False):
                    await handler()
                assert download.call_count == 1
    asyncio.run(check())
