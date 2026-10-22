"""실제 XLSX와 SQLCipher로 명부 검증, 전체 롤백, 작성자와 저장 필드 확인."""

from datetime import datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook
import pytest

from database import ConflictError, Database
from models import SchoolSettings, StudentInput, TeacherInput
from repositories.roster_import_repo import RosterImportRepository
from repositories.school_settings_repo import SchoolSettingsRepository
from repositories.student_repo import StudentRepository
from repositories.teacher_repo import TeacherRepository
from services.roster_import import COLUMNS, TITLES, import_template, parse_import


@pytest.fixture
def db(tmp_path):
    database = Database('import-key', tmp_path / 'import.db')
    database.initialize(SchoolSettings(counselor_name='작성교사'))
    return database


def xlsx(kind, rows, headers=None):
    book = Workbook()
    sheet = book.active
    sheet.title = TITLES[kind]
    sheet.append(headers or [label for _, label, _ in COLUMNS[kind]])
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


@pytest.mark.parametrize('kind', ['students', 'teachers'])
def test_template_has_only_headers_and_instructions(kind):
    book = load_workbook(BytesIO(import_template(kind)))
    sheet = book[TITLES[kind]]
    assert [cell.value for cell in sheet[1]] == [
        label + (' *' if needed else '') for _, label, needed in COLUMNS[kind]]
    assert sheet.freeze_panes == 'A2'
    assert all(cell.value is None for cell in sheet[2])
    assert sheet['C2'].number_format == '@'
    assert '작성 안내' in book.sheetnames
    # 서식 자체를 업로드해도 예시 인물이 등록되지 않는다.
    with pytest.raises(ValueError, match='등록할 데이터가 없습니다'):
        parse_import(import_template(kind), kind)
    book.close()


def test_student_round_trip_all_fields_excel_date_and_author(db):
    content = xlsx('students', [
        ['학생1', 2, '03', '0001', '별명', datetime(2012, 3, 4), '010-0012-0034', '010-9876-0000', '메모'],
        [None] * 9,
        ['학생2', 3, 1, None, None, '2011-01-01'],
    ])
    repository = RosterImportRepository(db)
    batch = repository.preview(content, 'students')
    assert not batch.errors
    assert [row.number for row in batch.rows] == [2, 4]
    assert StudentRepository(db).list() == []
    SchoolSettingsRepository(db).save(SchoolSettings(counselor_name='등록시 교사'))
    assert repository.save(batch) == 2
    first, second = StudentRepository(db).list()
    assert first.nickname == '별명'
    assert first.student_contact == '010-0012-0034'
    assert first.guardian_contact == '010-9876-0000'
    assert first.student_number == '0001'
    assert first.classroom == '03'
    assert first.birth_date.isoformat() == '2012-03-04'
    assert first.notes == '메모'
    assert first.author == '등록시 교사'
    assert second.student_number is None
    assert db.student_revision == 2


def test_teacher_round_trip_and_duplicates(db):
    repository = RosterImportRepository(db)
    content = xlsx('teachers', [['교사', '010-0012-0034', '0012', '2학년'], ['교사', '', '0013', '3학년']])
    batch = repository.preview(content, 'teachers')
    assert not batch.errors
    assert repository.save(batch) == 2
    teachers = TeacherRepository(db).list()
    assert [teacher.extension for teacher in teachers] == ['0012', '0013']
    assert all(teacher.author == '작성교사' for teacher in teachers)
    duplicate = repository.preview(content, 'teachers')
    assert len(duplicate.errors) == 2
    with pytest.raises(ValueError):
        repository.save(duplicate)
    assert len(TeacherRepository(db).list()) == 2


def test_row_errors_block_whole_file_and_report_original_rows(db):
    repository = RosterImportRepository(db)
    batch = repository.preview(xlsx('students', [
        ['정상', 1, 1, '001'], ['오류', 0, 1], ['수식', 1, 1, '=1+1'], ['중복', 2, 1, '001'],
    ]), 'students')
    assert len(batch.errors) == 3
    assert all(any(error.startswith(f'{row}행:') for error in batch.errors) for row in (3, 4, 5))
    with pytest.raises(ValueError):
        repository.save(batch)
    assert StudentRepository(db).list() == []


def test_existing_student_number_and_new_conflict_after_preview(db):
    repository = RosterImportRepository(db)
    content = xlsx('students', [['학생', 1, 1, '001']])
    batch = repository.preview(content, 'students')
    StudentRepository(db).create(StudentInput(name='기존 학생', grade=1, classroom='1', student_number='001'))
    assert repository.preview(content, 'students').errors
    with pytest.raises(ValueError, match='이미 등록된 학생 번호'):
        repository.save(batch)
    assert len(StudentRepository(db).list()) == 1


def test_batch_insert_rolls_back_all_rows_on_database_conflict(db):
    students = StudentRepository(db)
    with pytest.raises(ConflictError):
        students.create_many([
            StudentInput(name='첫 학생', grade=1, classroom='1', student_number='001'),
            StudentInput(name='두 학생', grade=2, classroom='2', student_number='001'),
        ])
    assert students.list() == []
    assert db.student_revision == 0


def test_teacher_batch_rolls_back_on_late_database_error(db):
    with db.session(write=True) as connection:
        connection.execute("""CREATE TRIGGER reject_teacher BEFORE INSERT ON teachers
            WHEN NEW.name='오류' BEGIN SELECT RAISE(ABORT, 'test'); END""")
    with pytest.raises(ConflictError):
        TeacherRepository(db).create_many([TeacherInput(name='정상'), TeacherInput(name='오류')])
    assert TeacherRepository(db).list() == []


def test_minimum_and_reordered_columns_and_leading_zeros():
    content = xlsx('students', [[1, '학생', 2]], headers=['반 *', '이름 *', '학년 *'])
    value = parse_import(content, 'students').rows[0].value
    assert value.name == '학생' and value.grade == 2 and value.classroom == '1'
    book = load_workbook(BytesIO(xlsx('teachers', [['교사', None, 12]])))
    book.active['C2'].number_format = '0000'
    stream = BytesIO()
    book.save(stream)
    assert parse_import(stream.getvalue(), 'teachers').rows[0].value.extension == '0012'
    book.close()


@pytest.mark.parametrize(('content', 'kind'), [
    (b'not an xlsx file', 'students'),
    (xlsx('teachers', [['교사']]), 'students'),
    (xlsx('students', [['학생', 1]], headers=['이름', '학년']), 'students'),
    (xlsx('teachers', [['교사']], headers=['알수없는열']), 'teachers'),
    (xlsx('teachers', [['교사', '중복']], headers=['이름', '이름']), 'teachers'),
])
def test_invalid_files_and_headers(content, kind):
    with pytest.raises(ValueError):
        parse_import(content, kind)


def test_student_optional_fields_migrate_and_survive_edits(db):
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    with db.session(write=True) as connection:
        connection.execute('ALTER TABLE students DROP COLUMN nickname')
        connection.execute('ALTER TABLE students DROP COLUMN student_contact')
        connection.execute('PRAGMA user_version=27')
    db.initialize()
    assert StudentRepository(db).get(student.id).nickname == ''
    updated = StudentRepository(db).update(student.id, StudentInput(
        name='학생', grade=1, classroom='1', nickname='별명', student_contact='010-1234-5678'))
    assert updated.nickname == '별명'
    assert updated.student_contact == '010-1234-5678'
    assert updated.author == student.author
