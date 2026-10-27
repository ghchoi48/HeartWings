"""일지 PDF 전용 조회. 비밀 메모·연락처·가족·첨부파일을 조회하지 않는다."""
import json
from datetime import datetime, time, timedelta

from maeumnarae.core.database import DatabaseError
from maeumnarae.services.reporting import KST
from maeumnarae.services.journal_print_models import KINDS, PrintRequest, PrintRecord, PrintSnapshot

# SQL 식별자는 아래 고정 매핑에서만 선택한다.
COMMON = 'r.id, r.title, r.author, r.duration_minutes'
COUNSELING = ', r.starts_at, r.status, r.content_markdown AS content, r.content_format, r.follow_up, r.category, r.counseling_area, r.counseling_method, r.counseling_target'
QUERIES = {
    'individual': (COMMON + COUNSELING + ', s.id AS subject_id, s.name AS subject, c.title AS case_title',
                   'counseling r JOIN students s ON s.id=r.student_id LEFT JOIN counseling_cases c ON c.id=r.case_id', 'student'),
    'special': (COMMON + COUNSELING + ', s.id AS subject_id, s.name AS subject, c.title AS case_title, c.law, c.case_number',
                'special_education_logs r JOIN students s ON s.id=r.student_id JOIN special_educations c ON c.id=r.case_id', 'student'),
    'group': (COMMON + ", r.starts_at, r.status, r.content_html AS content, 'html' AS content_format, r.follow_up, r.attendance, g.id AS subject_id, g.name AS subject, g.counseling_area",
              'group_counseling_logs r JOIN counseling_groups g ON g.id=r.group_id', 'group'),
    'consultation': (COMMON + ", r.starts_at, r.status, r.content_html AS content, 'html' AS content_format, r.follow_up, r.consultation_area, t.id AS subject_id, t.name AS subject",
                     'consultations r JOIN teachers t ON t.id=r.teacher_id', 'teacher'),
    'test': (COMMON + ', r.test_date AS day, r.test_time AS clock, r.content, r.content_format, r.target, s.id AS subject_id, s.name AS subject',
             'psychological_tests r JOIN students s ON s.id=r.student_id', 'student'),
    'education': (COMMON + ", r.event_date AS day, r.event_time AS clock, r.content, r.content_format, r.category, r.location, r.audience, r.participant_count, r.facilitator, 0 AS subject_id, '교육/행사' AS subject",
                  'education_events r', 'event'),
}
DETAILS = {'category': '유형', 'case_title': '사례/교육명', 'counseling_area': '상담 분야',
           'counseling_method': '상담 방법', 'counseling_target': '상담 대상', 'consultation_area': '자문 분야',
           'law': '근거 법률', 'case_number': '사건 번호', 'target': '검사 대상', 'location': '장소',
           'audience': '대상', 'participant_count': '참여 인원', 'facilitator': '담당자 / 강사'}


class JournalPrintRepository:
    def __init__(self, database):
        self.database = database

    def snapshot(self, request: PrintRequest) -> PrintSnapshot:
        request.validate()
        selected = set(request.refs)
        records = []
        with self.database.session() as connection:
            school = connection.execute('SELECT school_name FROM school_settings WHERE id=1').fetchone()
            for kind, (columns, source, subject_type) in QUERIES.items():
                ids = sorted(key for k, key in selected if k == kind)
                if request.school_year is None and not ids:
                    continue
                # ID를 나누어 조회해도 같은 읽기 트랜잭션을 유지한다.
                batches = [ids[i:i + 400] for i in range(0, len(ids), 400)] if ids else [None]
                for batch in batches:
                    where = ' WHERE r.id IN (' + ','.join('?' for _ in batch) + ')' if batch else ''
                    params = batch or ()
                    if request.school_year is not None:
                        start, stop = request.bounds
                        day_sql = ('r.test_date' if kind == 'test' else 'r.event_date' if kind == 'education'
                                   else "date(r.starts_at, '+9 hours')")
                        where = f' WHERE {day_sql} >= ? AND {day_sql} < ?'
                        # SQLite 날짜 함수의 밀리초 반올림으로 경계 기록을 잃지 않도록
                        # 하루 여유를 두고 아래 Python 검사에서 정확히 잘라낸다.
                        params = ((start - timedelta(days=1)).isoformat(), (stop + timedelta(days=1)).isoformat())
                        if kind not in ('test', 'education'):
                            if not request.statuses:
                                continue
                            where += ' AND r.status IN (' + ','.join('?' for _ in request.statuses) + ')'
                            params += request.statuses
                    for row in connection.execute(f'SELECT {columns} FROM {source}{where}', params):
                        data = dict(row)
                        moment = (datetime.fromisoformat(data['starts_at']).astimezone(KST) if 'starts_at' in data else
                                  datetime.combine(datetime.fromisoformat(data['day']).date(),
                                                   time.fromisoformat(data['clock'] or '00:00'), KST))
                        if request.school_year is not None:
                            start, stop = request.bounds
                            if not start <= moment.date() < stop:
                                continue
                            if 'status' in data and data['status'] not in request.statuses:
                                continue
                        records.append(PrintRecord(kind, data['id'], subject_type, data['subject_id'], data['subject'],
                            moment, data['title'], data['author'], data.get('status', ''), data['duration_minutes'],
                            data['content'], data['content_format'], data.get('follow_up', ''),
                            tuple((label, str(data[key])) for key, label in DETAILS.items() if data.get(key) not in (None, '')),
                            tuple(json.loads(data.get('attendance', '[]')))))
        if selected and {(r.kind, r.id) for r in records} != selected:
            raise DatabaseError('선택한 일지를 찾을 수 없습니다. 목록을 새로고침해 주세요.')
        order = list(KINDS)
        records.sort(key=lambda r: (order.index(r.kind), r.subject, r.subject_id, r.moment, r.id))
        return PrintSnapshot(school[0] if school else '', tuple(records))
