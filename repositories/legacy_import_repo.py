"""기존 XLSB 자료를 한 트랜잭션으로 추가한다."""

from dataclasses import replace

from models import StudentInput, TeacherInput, ConsultationInput, PsychologicalTestInput, CounselingInput, EducationEventInput
from repositories._support import now_text, values
from repositories.student_repo import StudentRepository
from services.legacy_import import parse_legacy


class LegacyImportRepository:
    def __init__(self, database):
        self.database = database

    def _resolve(self, connection, batch):
        errors = list(batch.errors)
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_imports'").fetchone()
        if exists and connection.execute('SELECT 1 FROM legacy_imports WHERE fingerprint=?', (batch.fingerprint,)).fetchone():
            errors.append('이미 가져온 원본 자료입니다.')
        existing = {}
        for row in connection.execute('''SELECT s.*, e.school_year AS match_year, e.grade AS match_grade,
                e.classroom AS match_classroom FROM students s JOIN student_enrollments e ON e.student_id=s.id'''):
            key = ('student', row['name'], row['match_year'], row['match_grade'], row['match_classroom'])
            existing.setdefault(key, []).append(dict(row))
        for kind, table in [('teacher', 'teachers'), ('group', 'counseling_groups')]:
            for row in connection.execute(f'SELECT * FROM {table}'):
                existing.setdefault((kind, row['name']), []).append(dict(row))
        source, resolutions, actions = {}, {}, []
        for person in batch.people:
            value = person.value
            if isinstance(value, StudentInput):
                identity = ('student', value.name, value.school_year, value.grade, value.classroom)
                fields = ('birth_date', 'gender', 'student_contact')
            elif isinstance(value, TeacherInput):
                identity, fields = ('teacher', value.name), ('contact',)
            else:
                identity, fields = ('group', value.name), ()
            data = values(value)

            def compatible(other):
                return all(not data.get(field) or not other.get(field) or data[field] == other[field] for field in fields)

            candidates = [row for row in existing.get(identity, []) if compatible(row)]
            if len(candidates) > 1 or (existing.get(identity) and not candidates):
                errors.append(f'인적사항등록 {person.row}행: 동일 대상 후보가 여러 명이거나 식별 정보가 충돌합니다.')
                continue
            # 같은 파일의 여러 사례번호도 같은 대상을 재사용한다.
            if identity in source:
                first_key, previous = source[identity]
                if not compatible(previous):
                    errors.append(f'인적사항등록 {person.row}행: 같은 대상의 식별 정보가 충돌합니다.')
                    continue
                previous.update({field: data[field] for field in fields if data.get(field)})
                resolutions[person.key] = resolutions[first_key]
                actions.append((person.key, '파일 내 동일 대상 연결'))
            else:
                source[identity] = (person.key, data)
                resolutions[person.key] = ('existing', candidates[0]['id']) if candidates else ('new', person.key)
                actions.append((person.key, '기존 DB 대상 연결' if candidates else '신규 등록'))
        return errors, resolutions, tuple(actions)

    def preview(self, content, school_year, period_times=None, **options):
        batch = parse_legacy(content, school_year, period_times, **options)
        with self.database.session() as connection:
            errors, _, actions = self._resolve(connection, batch)
            return replace(batch, errors=tuple(errors), actions=actions)

    def save(self, batch):
        if batch.errors or not (batch.people or batch.logs):
            raise ValueError('파일 오류를 수정하고 다시 검사하세요.')
        with self.database.session(write=True) as connection:
            errors, resolutions, _ = self._resolve(connection, batch)
            if errors:
                raise ValueError('\n'.join(errors[:30]))
            # 이관 이력 역시 암호화된 DB에 보관하고 데이터와 함께 커밋한다.
            connection.execute('''CREATE TABLE IF NOT EXISTS legacy_imports (
                fingerprint TEXT PRIMARY KEY, imported_at TEXT NOT NULL)''')
            ids, cases, created = {}, {}, 0
            special_cases = {}
            timestamp = now_text()

            def insert(table, data):
                # 테이블/열은 코드 내 모델로만 구성한다. 원본 값은 모두 바인딩한다.
                data = dict(data, created_at=timestamp, updated_at=timestamp)
                columns = ','.join(data)
                return connection.execute(f'INSERT INTO {table} ({columns}) VALUES ({",".join("?" for _ in data)})',
                                          tuple(data.values())).lastrowid

            for person in batch.people:
                mode, target = resolutions[person.key]
                if mode == 'existing':
                    ids[person.key] = target
                    continue
                if target != person.key:
                    ids[person.key] = ids[target]
                    continue
                data = values(person.value)
                if isinstance(person.value, StudentInput):
                    ids[person.key] = insert('students', data)
                    StudentRepository._save_enrollment(connection, ids[person.key], data)
                elif isinstance(person.value, TeacherInput):
                    ids[person.key] = insert('teachers', data)
                else:
                    data.pop('student_ids')
                    ids[person.key] = insert('counseling_groups', data)
                created += 1
            for log in batch.logs:
                data = values(log.value)
                if log.author:
                    data['author'] = log.author
                if isinstance(log.value, EducationEventInput):
                    table = 'education_events'
                elif isinstance(log.value, ConsultationInput):
                    data['teacher_id'] = ids[log.key]
                    table = 'consultations'
                elif isinstance(log.value, PsychologicalTestInput):
                    data['student_id'] = ids[log.key]
                    table = 'psychological_tests'
                elif isinstance(log.value, CounselingInput) and log.special_law:
                    case_key = (log.key, log.special_law)
                    if case_key not in special_cases:
                        special_cases[case_key] = insert('special_educations', dict(
                            student_id=ids[log.key], title=f'이관 특별교육 {log.key}'[:200],
                            law=log.special_law, case_number=log.key[:100]))
                    data.update(student_id=ids[log.key], case_id=special_cases[case_key])
                    data.pop('private_note_html')
                    table = 'special_education_logs'
                elif isinstance(log.value, CounselingInput):
                    if log.key not in cases:
                        cases[log.key] = insert('counseling_cases', dict(student_id=ids[log.key], title=f'이관 사례 {log.key}'[:200]))
                    data.update(student_id=ids[log.key], case_id=cases[log.key])
                    table = 'counseling'
                else:
                    data['group_id'] = ids[log.key]
                    table = 'group_counseling_logs'
                log_id = insert(table, data)
                # 일반 작성자 트리거는 현재 교사를 기록한다. 이관은 원본 작성자를 보존한다.
                if log.author:
                    connection.execute(f'UPDATE {table} SET author=? WHERE id=?', (log.author, log_id))
            connection.execute('INSERT INTO legacy_imports VALUES (?, ?)', (batch.fingerprint, timestamp))
        self.database.student_revision += 1
        return created, len(batch.logs)

    def load_period_times(self):
        import json
        with self.database.session() as connection:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_import_settings'").fetchone():
                return {}
            row = connection.execute('SELECT period_times FROM legacy_import_settings WHERE id=1').fetchone()
            return json.loads(row[0]) if row else {}

    def save_period_times(self, periods):
        import json
        from services.legacy_import import period_clocks
        normalized = {key: value.strftime('%H:%M') for key, value in period_clocks(periods).items()}
        with self.database.session(write=True) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS legacy_import_settings (id INTEGER PRIMARY KEY, period_times TEXT NOT NULL)')
            connection.execute('INSERT OR REPLACE INTO legacy_import_settings VALUES (1, ?)',
                               (json.dumps(normalized),))
