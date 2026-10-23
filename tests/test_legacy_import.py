"""익명 데이터와 임시 암호화 DB로 이관/재등록/롤백을 검증한다."""

from datetime import date

import pytest

from database import Database
from models import SchoolSettings, StudentInput
from repositories.legacy_import_repo import LegacyImportRepository
from repositories.student_repo import StudentRepository
from services.legacy_import import PERSON_HEADERS, LOG_HEADERS, parse_rows, read_rows

PERIODS = {'1': '10:30', '2': '13:20'}


def record(headers, **fields):
    return dict.fromkeys(headers, '') | fields


def source():
    return {
        '인적사항등록': [
            (7, record(PERSON_HEADERS, 사례번호='P1', **{'성명/집단명': '학생A', '성별/인원': '여'},
                       학년=2, 반=3, 생년월일=41000, 학생연락처='010-0000-0001')),
            (8, record(PERSON_HEADERS, 사례번호='G1', **{'성명/집단명': '집단A', '성별/인원': 5})),
        ],
        '상담대장': [
            (5, record(LOG_HEADERS, 사례번호='P1', 일자=46000, 상담제목='개인 제목',
                       상담내용='<script>alert(1)</script>\n기록', 상담자성명='원본 교사', 교시=1.0,
                       **{'시간(시)': 0, '시간(분)': 40})),
            (6, record(LOG_HEADERS, 사례번호='G1', 일자='2025-12-10', 상담제목='집단 제목', 교시='2교시',
                       **{'시간(시)': 1, '시간(분)': 30})),
        ],
    }


@pytest.fixture
def db(tmp_path):
    database = Database('test-key', tmp_path / 'legacy.db')
    database.initialize(SchoolSettings(counselor_name='현재 교사'))
    return database


def test_roundtrip_and_duplicate(db):
    batch = parse_rows(source(), 2025, PERIODS)
    assert not batch.errors
    assert batch.people[0].value.birth_date == date(2012, 4, 1)
    repository = LegacyImportRepository(db)
    assert repository.save(batch) == (2, 2)
    with db.session() as c:
        student = c.execute('SELECT * FROM students').fetchone()
        assert student['student_contact'] == '010-0000-0001'
        assert c.execute('SELECT school_year FROM student_enrollments').fetchone()[0] == 2025
        log = c.execute('SELECT * FROM counseling').fetchone()
        assert log['student_id'] == student['id']
        assert log['author'] == '원본 교사'
        assert log['duration_minutes'] == 40
        assert 'T01:30:00' in log['starts_at']
        assert '&lt;script&gt;' in log['content_markdown']
        assert '<script>' not in log['content_markdown']
        group_log = c.execute('SELECT * FROM group_counseling_logs').fetchone()
        assert group_log['duration_minutes'] == 90
        assert 'T04:20:00' in group_log['starts_at']
    with pytest.raises(ValueError, match='이미 가져온'):
        repository.save(batch)


def test_missing_link_and_duplicate_case_block_whole_batch(db):
    rows = source()
    rows['상담대장'][0][1]['사례번호'] = 'missing'
    rows['인적사항등록'].append(rows['인적사항등록'][0])
    batch = parse_rows(rows, 2025, PERIODS)
    assert len(batch.errors) == 1
    with pytest.raises(ValueError):
        LegacyImportRepository(db).save(batch)
    assert StudentRepository(db).list() == []


def test_atomic_rollback_after_student_insert(db):
    batch = parse_rows(source(), 2025, PERIODS)
    # 실제 SQL 오류를 개인 저장 이후의 집단 일지에서 일으킨다.
    with db.session(write=True) as c:
        c.execute("CREATE TRIGGER fail_legacy BEFORE INSERT ON group_counseling_logs BEGIN SELECT RAISE(ABORT, 'test'); END")
    from database import DatabaseError
    with pytest.raises(DatabaseError):
        LegacyImportRepository(db).save(batch)
    with db.session() as c:
        for table in ('students', 'student_enrollments', 'counseling', 'counseling_groups', 'counseling_cases'):
            assert c.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_imports'").fetchone() is None


def test_existing_student_conflict(db):
    batch = parse_rows(source(), 2025, PERIODS)
    StudentRepository(db).create(StudentInput(name='학생A', school_year=2025, grade=2, classroom='3', gender='남'))
    with pytest.raises(ValueError, match='식별 정보가 충돌'):
        LegacyImportRepository(db).save(batch)


def test_empty_invalid_dates_and_options():
    assert parse_rows({'인적사항등록': [], '상담대장': []}, 2025).errors
    rows = source()
    rows['상담대장'][0][1]['일자'] = 0
    assert parse_rows(rows, 2025).errors
    with pytest.raises(ValueError):
        parse_rows(source(), 2025.5)
    with pytest.raises(ValueError):
        parse_rows(source(), 2025, {'1': '25:00'})
    with pytest.raises(ValueError):
        read_rows(b'not xlsb')


def test_header_detection_and_formula_only_rows(monkeypatch):
    from collections import namedtuple
    from contextlib import nullcontext
    from io import BytesIO
    from zipfile import ZipFile
    import services.legacy_import as module
    Cell = namedtuple('Cell', 'r c v')

    class Sheet:
        dimension = namedtuple('Dimension', 'h w')(20, 30)

        def __init__(self, headers):
            self.headers = headers

        def rows(self, sparse=False):
            yield [Cell(3, n, h) for n, h in enumerate(self.headers)]
            yield [Cell(4, n, {'접수': 1, '학년도': 1900, '상담일자': 0}.get(h, ''))
                   for n, h in enumerate(self.headers)]

    class Book:
        def get_sheet(self, name):
            return nullcontext(Sheet(PERSON_HEADERS if name == '인적사항등록' else LOG_HEADERS))

    monkeypatch.setattr(module, 'open_workbook', lambda _: nullcontext(Book()))
    stream = BytesIO()
    with ZipFile(stream, 'w') as z:
        z.writestr('fake', '')
    assert read_rows(stream.getvalue()) == {'인적사항등록': [], '상담대장': []}


@pytest.mark.parametrize('hours,minutes,expected', [
    (1, 30, 90), ('', 45, 45), (2, '', 120), (0.5, 15, 45), (0, 90, 90), (24, 0, 1440),
])
def test_duration_conversion(hours, minutes, expected):
    rows = source()
    rows['상담대장'][0][1].update({'시간(시)': hours, '시간(분)': minutes, '교시': '01교시'})
    batch = parse_rows(rows, 2025, PERIODS)
    assert not batch.errors
    assert batch.logs[0].value.duration_minutes == expected
    assert batch.logs[0].value.starts_at.hour == 10
    assert batch.logs[0].value.starts_at.minute == 30


@pytest.mark.parametrize('hours,minutes', [('', ''), (0, 0), (-1, 90), (1, -5),
    ('문자', 30), ('NaN', 1), ('Infinity', 0), (24, 1), (0, 0.5)])
def test_invalid_duration_has_row_error(hours, minutes):
    rows = source()
    rows['상담대장'][0][1].update({'시간(시)': hours, '시간(분)': minutes})
    batch = parse_rows(rows, 2025, PERIODS)
    assert len(batch.errors) == 1
    assert batch.errors[0].startswith('상담대장 5행: 시간(시)')


@pytest.mark.parametrize('period', ['', '8교시', '점심'])
def test_unconfigured_period_is_not_guessed(period):
    rows = source()
    rows['상담대장'][0][1]['교시'] = period
    batch = parse_rows(rows, 2025, PERIODS)
    assert len(batch.errors) == 1
    assert '교시' in batch.errors[0]


def test_named_period_and_duplicate_mapping():
    rows = source()
    rows['상담대장'][0][1]['교시'] = '점심'
    batch = parse_rows(rows, 2025, PERIODS | {'점심': '12:40'})
    assert not batch.errors
    assert batch.logs[0].value.starts_at.hour == 12
    with pytest.raises(ValueError, match='중복'):
        parse_rows(rows, 2025, {'1': '09:00', '1교시': '10:00'})


def consultation_source():
    rows = source()
    rows['인적사항등록'][0][1].update({'성명/집단명': '교사A', '학년': '', '반': '', '비고': '원본 교사 메모'})
    rows['상담대장'][0][1].update({'대분류': ' 자문 ', '중분류': '교원자문', '상담구분': '학교학습', '성명/집단명': '교사A'})
    return rows


def test_consultation_import_links_teacher_and_preserves_fields(db):
    from models import TeacherInput, ConsultationInput
    from repositories.consultation_repo import ConsultationRepository
    rows = consultation_source()
    second = dict(rows['상담대장'][0][1], 상담제목='두 번째 자문', 중분류='원본 영역', 상담구분='기타')
    rows['상담대장'].append((7, second))
    batch = parse_rows(rows, 2025, PERIODS)
    assert not batch.errors
    assert isinstance(batch.people[0].value, TeacherInput)
    assert isinstance(batch.logs[0].value, ConsultationInput)
    assert LegacyImportRepository(db).save(batch) == (2, 3)
    with db.session() as c:
        assert c.execute('SELECT count(*) FROM students').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM counseling').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM counseling_cases').fetchone()[0] == 0
        teacher = c.execute('SELECT * FROM teachers').fetchone()
        assert teacher['name'] == '교사A'
        assert teacher['contact'] == '010-0000-0001'
        assert c.execute('SELECT count(*) FROM teachers').fetchone()[0] == 1
        assert c.execute('SELECT count(*) FROM group_counseling_logs').fetchone()[0] == 1
    logs = ConsultationRepository(db).list(teacher['id'])
    assert len(logs) == 2
    assert all(log.author == '원본 교사' and log.duration_minutes == 40 for log in logs)
    assert {log.consultation_area for log in logs} == {'학교학습', '기타'}
    assert all('원본 교사 메모' not in log.content_html and '&lt;script&gt;' in log.content_html for log in logs)
    with pytest.raises(ValueError, match='이미 가져온'):
        LegacyImportRepository(db).save(batch)


def test_mixed_consultation_and_counseling_case_is_blocked():
    rows = consultation_source()
    rows['상담대장'].append((7, dict(rows['상담대장'][0][1], 대분류='상담')))
    assert any('혼재' in error for error in parse_rows(rows, 2025, PERIODS).errors)


def test_consultation_failure_rolls_back_teacher_and_other_records(db):
    from database import DatabaseError
    with db.session(write=True) as c:
        c.execute("CREATE TRIGGER fail_consultation BEFORE INSERT ON consultations BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(DatabaseError):
        LegacyImportRepository(db).save(parse_rows(consultation_source(), 2025, PERIODS))
    with db.session() as c:
        for table in ('teachers', 'consultations', 'counseling_groups'):
            assert c.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_existing_teacher_name_blocks_automatic_merge(db):
    from models import TeacherInput
    from repositories.teacher_repo import TeacherRepository
    TeacherRepository(db).create_many([TeacherInput(name='교사A', contact='010-9999-9999')])
    with pytest.raises(ValueError, match='식별 정보가 충돌'):
        LegacyImportRepository(db).save(parse_rows(consultation_source(), 2025, PERIODS))


@pytest.mark.parametrize('target,expected', [('학생', '학생'), ('보호자(가족)', '보호자(학부모)')])
def test_psychological_test_migration(db, target, expected):
    from models import PsychologicalTestInput
    from repositories.psychological_test_repo import PsychologicalTestRepository
    rows = source()
    rows['상담대장'][0][1].update({'상담구분': ' 개인심리검사 ', '대상': target, '대분류': '자문'})
    batch = parse_rows(rows, 2025, PERIODS)
    assert not batch.errors
    assert isinstance(batch.logs[0].value, PsychologicalTestInput)
    LegacyImportRepository(db).save(batch)
    with db.session() as c:
        student_id = c.execute('SELECT id FROM students').fetchone()[0]
        assert c.execute('SELECT count(*) FROM counseling').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM counseling_cases').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM consultations').fetchone()[0] == 0
    log = PsychologicalTestRepository(db).list(student_id)[0]
    assert log.target == expected
    assert log.test_date == batch.logs[0].value.test_date
    assert log.test_time == '10:30'
    assert log.duration_minutes == 40
    assert log.author == '원본 교사'
    assert log.content_format == 'html'
    assert '&lt;script&gt;' in log.content


@pytest.mark.parametrize('category,expected', [('학생관련상담', '학생관련상담'), ('교사관련상담', '교사관련상담'),
    ('학습', '학습'), ('기타', '기타'), ('원본 기타 구분', '기타')])
def test_guardian_migration_uses_category_for_area(db, category, expected):
    rows = source()
    rows['상담대장'][0][1].update({'중분류': '학부모상담', '상담구분': category, '대상': '학생'})
    batch = parse_rows(rows, 2025, PERIODS)
    assert not batch.errors
    LegacyImportRepository(db).save(batch)
    with db.session() as c:
        row = c.execute('SELECT * FROM counseling').fetchone()
        assert row['counseling_target'] == '보호자(가족)'
        assert row['counseling_area'] == expected
        assert row['category'] == '학부모상담'
        assert category not in row['content_markdown']


def test_individual_test_rejects_group_and_rolls_back_on_failure(db):
    from database import DatabaseError
    rows = source()
    rows['상담대장'][1][1]['상담구분'] = '개인심리검사'
    assert any('학생 인적사항' in error for error in parse_rows(rows, 2025, PERIODS).errors)
    rows = source()
    rows['상담대장'][0][1]['상담구분'] = '개인심리검사'
    with db.session(write=True) as c:
        c.execute("CREATE TRIGGER fail_test BEFORE INSERT ON psychological_tests BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(DatabaseError):
        LegacyImportRepository(db).save(parse_rows(rows, 2025, PERIODS))
    with db.session() as c:
        assert c.execute('SELECT count(*) FROM students').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM psychological_tests').fetchone()[0] == 0


@pytest.mark.parametrize('major', ['교육', '연구', '의뢰'])
@pytest.mark.parametrize('route', ['개인 상담', '교사 자문', '심리검사', '교육/행사'])
def test_manual_destination_and_original_fingerprint(major, route):
    from models import CounselingInput, ConsultationInput, PsychologicalTestInput, EducationEventInput
    rows = source()
    rows['상담대장'][0][1]['대분류'] = major
    initial = parse_rows(rows, 2025, PERIODS)
    assert any('일지를 직접 선택' in error for error in initial.errors)
    batch = parse_rows(rows, 2025, PERIODS, destinations={5: route})
    assert not batch.errors
    assert isinstance(batch.logs[0].value, {'개인 상담': CounselingInput, '교사 자문': ConsultationInput,
                      '심리검사': PsychologicalTestInput, '교육/행사': EducationEventInput}[route])
    assert batch.fingerprint == initial.fingerprint


def test_group_test_event_without_people_and_atomic_save(db):
    from models import EducationEventInput
    rows = source()
    rows['인적사항등록'] = []
    rows['상담대장'] = [rows['상담대장'][1]]
    rows['상담대장'][0][1].update(대분류='검사', 중분류='심리검사', 상담구분='집단심리검사', 상담인원=12,
                                  상담내용='검사 내용', 상담자성명='검사 교사')
    batch = parse_rows(rows, 2025, PERIODS)
    assert not batch.errors
    assert isinstance(batch.logs[0].value, EducationEventInput)
    assert LegacyImportRepository(db).save(batch) == (0, 1)
    with db.session() as connection:
        event = connection.execute('SELECT * FROM education_events').fetchone()
        assert event['category'] == '단체심리검사'
        assert event['participant_count'] == 12
        assert event['event_time'] == '13:20'
        assert event['author'] == '검사 교사'
        assert event['content'] == '<p>검사 내용</p>'
    with pytest.raises(ValueError, match='이미 가져온'):
        LegacyImportRepository(db).save(batch)


def test_correction_exclusion_and_notes(db):
    from copy import deepcopy
    rows = source()
    rows['상담대장'][0][1]['일자'] = '잘못된 날짜'
    rows['인적사항등록'][0][1]['비고'] = '실제 비고'
    original = deepcopy(rows)
    batch = parse_rows(rows, 2025, PERIODS,
        corrections={('상담대장', 5): {'일자': '2025-12-10', '상담내용': '수정 내용'}},
        excluded={('상담대장', 6), ('인적사항등록', 8)})
    assert not batch.errors
    assert rows == original
    assert len(batch.logs) == len(batch.people) == 1
    assert batch.people[0].value.notes == '실제 비고'
    assert batch.logs[0].value.content_markdown == '<p>수정 내용</p>'
    assert batch.fingerprint == parse_rows(rows, 2025, PERIODS).fingerprint
    LegacyImportRepository(db).save(batch)
    with pytest.raises(ValueError, match='이미 가져온'):
        LegacyImportRepository(db).save(parse_rows(rows, 2025, PERIODS,
            corrections={('상담대장', 5): {'일자': '2025-12-11'}}))


def test_period_settings_persist_and_invalid_update_preserves_previous(db):
    repository = LegacyImportRepository(db)
    assert repository.load_period_times() == {}
    repository.save_period_times({'01교시': '08:50', '점심': '12:30'})
    assert LegacyImportRepository(db).load_period_times() == {'1': '08:50', '점심': '12:30'}
    with pytest.raises(ValueError):
        repository.save_period_times({'1': '25:00'})
    assert repository.load_period_times()['1'] == '08:50'


@pytest.mark.parametrize('major', ['교육', '연구', '의뢰'])
@pytest.mark.parametrize('law', ['학교폭력예방법', '교원지위법'])
def test_special_education_destination_saves_separate_case_and_logs(db, major, law):
    rows = source()
    rows['상담대장'][0][1]['대분류'] = major
    rows['상담대장'].append((7, dict(rows['상담대장'][0][1], 상담제목='두 번째 교육')))
    batch = parse_rows(rows, 2025, PERIODS, destinations={5: '특별교육', 7: '특별교육'},
                       special_laws={5: law, 7: law})
    assert not batch.errors
    assert batch.logs[0].special_law == law
    LegacyImportRepository(db).save(batch)
    with db.session() as c:
        case = c.execute('SELECT * FROM special_educations').fetchone()
        assert case['law'] == law and case['case_number'] == 'P1'
        assert c.execute('SELECT count(*) FROM special_educations').fetchone()[0] == 1
        logs = c.execute('SELECT * FROM special_education_logs').fetchall()
        assert len(logs) == 2
        assert all(log['case_id'] == case['id'] and log['student_id'] == case['student_id'] for log in logs)
        assert logs[0]['author'] == '원본 교사'
        assert logs[0]['duration_minutes'] == 40
        assert '&lt;script&gt;' in logs[0]['content_markdown']
        assert c.execute('SELECT count(*) FROM counseling').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM counseling_cases').fetchone()[0] == 0


def test_special_education_requires_student_and_law():
    assert any('근거 법률' in error for error in
               parse_rows(source(), 2025, PERIODS, destinations={5: '특별교육'}).errors)
    assert any('학생 인적사항' in error for error in
               parse_rows(source(), 2025, PERIODS, destinations={6: '특별교육'},
                          special_laws={6: '교원지위법'}).errors)


def test_special_education_import_failure_rolls_back(db):
    from database import DatabaseError
    batch = parse_rows(source(), 2025, PERIODS, destinations={5: '특별교육'}, special_laws={5: '교원지위법'})
    with db.session(write=True) as c:
        c.execute("CREATE TRIGGER fail_special BEFORE INSERT ON special_education_logs BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(DatabaseError):
        LegacyImportRepository(db).save(batch)
    with db.session() as c:
        for table in ('students', 'special_educations', 'special_education_logs'):
            assert c.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


@pytest.mark.parametrize('middle,area,expected_type', [
    ('개인상담', '진로', '개인상담'),
    ('개인상담', '대인관계', '개인상담'),
    ('', '학업', '개인상담'),
    ('개인상담', '', '개인상담'),
])
@pytest.mark.parametrize('manual', [False, True])
def test_individual_import_maps_area_and_type_to_correct_fields(db, middle, area, expected_type, manual):
    rows = source()
    rows['상담대장'][0][1].update(대분류='교육' if manual else '상담', 중분류=middle, 상담구분=area)
    batch = parse_rows(rows, 2025, PERIODS, destinations={5: '개인 상담'} if manual else None)
    assert not batch.errors
    assert batch.logs[0].value.counseling_area == area
    assert batch.logs[0].value.category == expected_type
    LegacyImportRepository(db).save(batch)
    with db.session() as connection:
        saved = connection.execute('SELECT * FROM counseling').fetchone()
        assert saved['counseling_area'] == area
        assert saved['category'] == expected_type
