"""캘린더의 간단한 입력을 기존 예약 일지로 저장한다."""
from html import escape

from maeumnarae.core.models import CounselingInput, ConsultationInput, GroupLogInput
from maeumnarae.repositories.journals.case_repo import CaseRepository
from maeumnarae.repositories.journals.counseling_repo import CounselingRepository
from maeumnarae.repositories.journals.consultation_repo import ConsultationRepository
from maeumnarae.repositories.journals.group_counseling_repo import GroupCounselingRepository
from maeumnarae.repositories.journals.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from maeumnarae.repositories.students.student_repo import StudentRepository
from maeumnarae.repositories.students.teacher_repo import TeacherRepository

KINDS = {'individual': '개인상담', 'group': '집단상담', 'consultation': '교직원 자문',
         'special_education': '특별교육'}


def save_reservation(database, *, kind, owner_id, case_id=None, title, starts_at,
                     duration_minutes, content=''):
    """대상을 검증하고 한 종류의 일지만 생성한다. DB 제약도 연결 관계를 보호한다."""
    if kind not in KINDS or not owner_id:
        raise ValueError('일지 종류와 연결 대상을 선택해 주세요.')
    if not 2 <= starts_at.year <= 9998:
        raise ValueError('날짜를 확인해 주세요.')
    html = escape(content).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>')
    common = dict(title=title, starts_at=starts_at, duration_minutes=duration_minutes,
                  status='scheduled')
    if kind in ('individual', 'special_education'):
        if StudentRepository(database).get(owner_id) is None:
            raise ValueError('학생이 존재하지 않습니다. 다시 선택해 주세요.')
        cases = (CaseRepository(database).list(owner_id) if kind == 'individual'
                 else SpecialEducationRepository(database).list(owner_id))
        if case_id is None:
            if kind == 'special_education' or cases:
                raise ValueError('상담 사례 또는 특별교육을 선택해 주세요.')
        elif not any(case.id == case_id for case in cases):
            raise ValueError('선택한 학생의 상담 사례 또는 특별교육이 아닙니다. 다시 선택해 주세요.')
        value = CounselingInput(**common, student_id=owner_id, case_id=case_id,
                                category='개인상담' if kind == 'individual' else '특별교육',
                                counseling_target='학생본인' if kind == 'individual' else '',
                                content_markdown=html, content_format='html')
        repository = (CounselingRepository(database) if kind == 'individual'
                      else SpecialEducationLogRepository(database))
        return repository.create(value)
    if kind == 'group':
        repository = GroupCounselingRepository(database)
        if repository.get(owner_id) is None:
            raise ValueError('집단이 존재하지 않습니다. 먼저 집단을 등록해 주세요.')
        return repository.save_log(GroupLogInput(**common, group_id=owner_id, content_html=html))
    if TeacherRepository(database).get(owner_id) is None:
        raise ValueError('교직원이 존재하지 않습니다. 다시 선택해 주세요.')
    return ConsultationRepository(database).save(
        ConsultationInput(**common, teacher_id=owner_id, content_html=html))


def reservation_options(database):
    """본문 없이 선택에 필요한 라벨만 읽으며 목록 개수를 제한하지 않는다."""
    with database.session() as connection:
        students = {row['id']: f"{row['name']} · {row['grade']}학년 {row['classroom']}반 · 번호 {row['student_number'] or '미입력'} (#{row['id']})"
                    for row in connection.execute('SELECT id, name, grade, classroom, student_number FROM students ORDER BY grade, classroom, name, id')}
        teachers = {row['id']: f"{row['name']} · {row['responsibilities'] or '담당 업무 미입력'} (#{row['id']})"
                    for row in connection.execute('SELECT id, name, responsibilities FROM teachers ORDER BY name, id')}
        groups = {row['id']: f"{row['name']} (#{row['id']})"
                  for row in connection.execute('SELECT id, name FROM counseling_groups ORDER BY id DESC')}
    return students, teachers, groups
