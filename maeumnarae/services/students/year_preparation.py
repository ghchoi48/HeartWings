"""DB와 UI에 의존하지 않는 새 학년도 명부 검토 초안."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from maeumnarae.core.models import StudentInput, TeacherInput
from maeumnarae.services.students.roster_import import ImportBatch


@dataclass
class DraftRow:
    key: str
    source: dict
    person_id: int | None = None
    candidates: tuple[int, ...] = ()
    confirmed: bool = True
    replacement_id: int | None = None
    edits: dict = field(default_factory=dict)


@dataclass
class YearDraft:
    kind: str
    base_year: int
    max_grade: int
    people: dict[int, dict]
    enrollments: dict[tuple[int, int], dict]
    rows: list[DraftRow]
    snapshot: str
    missing_edits: dict[int, dict] = field(default_factory=dict)
    retained_ids: set[int] = field(default_factory=set)
    consumed: bool = False

    @property
    def target_year(self):
        return self.base_year + 1

    def previous(self, person_id):
        value = dict(self.people[person_id])
        if self.kind == 'students':
            enrollment = self.enrollments.get((person_id, self.target_year)) or self.enrollments.get((person_id, self.base_year))
            value.update(enrollment or {})
        return value

    def link(self, key, person_id=None, replacement_id=None):
        row = next(row for row in self.rows if row.key == key)
        for selected in (person_id, replacement_id):
            if selected is not None and selected not in self.people:
                raise ValueError('기존 인원을 찾을 수 없습니다.')
        if person_id is not None and replacement_id is not None:
            raise ValueError('동일인 연결과 다른 사람 지정은 동시에 할 수 없습니다.')
        if replacement_id is not None and self.kind != 'teachers':
            raise ValueError('교사만 교체 대상을 지정할 수 있습니다.')
        occupied = {p for other in self.rows if other.key != key
                    for p in (other.person_id, other.replacement_id) if p is not None}
        if any(p in occupied for p in (person_id, replacement_id) if p is not None):
            raise ValueError('이미 다른 행에 지정된 인원입니다.')
        row.person_id, row.replacement_id = person_id, replacement_id
        row.confirmed = True
        row.edits.clear()
        if person_id in self.retained_ids:
            row.edits['status'] = '재학'

    def retain(self, person_id):
        """유예 재매칭 후보를 반환한다. 모호한 경우 UI에서 직접 연결한다."""
        self.retained_ids.add(person_id)
        self.missing_edits.setdefault(person_id, {})['status'] = '재학'
        old = self.previous(person_id)
        candidates = [r for r in self.rows if r.person_id is None
                      and r.source['name'] == old['name'] and r.source['grade'] == old['grade']]
        peers = [pid for pid in self.people if self.previous(pid)['name'] == old['name']
                 and self.previous(pid)['grade'] == old['grade']]
        if len(candidates) == len(peers) == 1:
            self.link(candidates[0].key, person_id)
        else:
            for row in candidates:
                row.candidates = tuple(dict.fromkeys((*row.candidates, *peers)))
                row.confirmed = False
        return candidates

    def entries(self):
        result = []
        linked = {r.person_id for r in self.rows if r.person_id is not None}
        replaced = {r.replacement_id for r in self.rows if r.replacement_id is not None}
        fields = StudentInput.model_fields if self.kind == 'students' else TeacherInput.model_fields
        for row in self.rows:
            before = self.previous(row.person_id) if row.person_id is not None else {}
            value = {k: v for k, v in before.items() if k in fields}
            if self.kind == 'students' and before:
                value.update({k: v for k, v in row.source.items()
                              if k in ('name', 'school_year', 'grade', 'classroom', 'student_number', 'status') or v not in ('', None)})
            else:
                value.update(row.source)
            value.update(row.edits)
            if self.kind == 'students':
                value['school_year'] = self.target_year
                if row.person_id and value.get('status') != '재학':
                    base = self.enrollments.get((row.person_id, self.base_year))
                    value['grade'] = (base or before)['grade']
                if value.get('status') in ('졸업', '조기졸업', '자퇴', '전학'):
                    value['grade'] = None
            action = ('신규' if row.person_id is None else '진급') if self.kind == 'students' else ('신규' if row.person_id is None else '갱신')
            if self.kind == 'students' and value.get('status') != '재학':
                action = value['status']
            elif self.kind == 'students' and row.person_id in self.retained_ids:
                action = '유예'
            result.append(dict(key=row.key, person_id=row.person_id, before=before, value=value,
                               action=action, confirmed=row.confirmed, error=''))
        for pid in self.people:
            if pid in linked:
                continue
            before = self.previous(pid)
            value = {k: v for k, v in before.items() if k in fields}
            if self.kind == 'teachers':
                value.update(extension='인사이동(전출)', responsibilities='')
                if pid not in replaced:
                    value['contact'] = ''
                action, confirmed = '전출', True
            else:
                base = self.enrollments.get((pid, self.base_year), {})
                status = '졸업' if base.get('grade') == self.max_grade else ''
                value.update(school_year=self.target_year, grade=(base or before)['grade'],
                             status=status, classroom='', student_number=None)
                action, confirmed = status or '미해결', bool(status)
            value.update(self.missing_edits.get(pid, {}))
            if self.kind == 'students':
                if value.get('status') in ('졸업', '조기졸업', '자퇴', '전학'):
                    value['grade'] = None
                action = value.get('status') or '미해결'
                if value.get('status') == '재학' and pid in self.retained_ids:
                    action = '유예'
                confirmed = bool(value.get('status'))
            result.append(dict(key=f'old:{pid}', person_id=pid, before=before, value=value,
                               action=action, confirmed=confirmed, error=''))
        return result

    def validate(self):
        entries = self.entries()
        numbers = {}
        ids = Counter(p for r in self.rows for p in (r.person_id, r.replacement_id) if p is not None)
        model = StudentInput if self.kind == 'students' else TeacherInput
        for entry in entries:
            errors = []
            if not entry['confirmed']:
                errors.append('동일인 또는 누락 상태를 확인하세요.')
            if ids[entry['person_id']] > 1:
                errors.append('기존 인원이 여러 행에 연결되었습니다.')
            try:
                value = model.model_validate(entry['value'])
                if self.kind == 'students':
                    if value.grade is not None and not 1 <= value.grade <= self.max_grade:
                        errors.append('학교급에 맞는 학년을 선택하세요.')
                    if value.status == '재학' and entry['person_id'] in self.retained_ids:
                        base = self.enrollments.get((entry['person_id'], self.base_year))
                        if base and value.grade != base['grade']:
                            errors.append('유예 학생은 기준 학년도와 같은 학년이어야 합니다.')
                    if value.student_number:
                        identity = (value.grade, value.classroom, value.student_number)
                        if identity in numbers:
                            errors.append('대상 학년도의 학반·번호가 중복됩니다.')
                            numbers[identity]['error'] = '대상 학년도의 학반·번호가 중복됩니다.'
                        numbers[identity] = entry
            except ValueError:
                errors.append('필수값·학적 상태·입력 형식과 길이를 확인하세요.')
            entry['error'] = ' '.join(filter(None, [entry['error'], *errors]))
        return entries


def prepare_draft(batch: ImportBatch, base_year, max_grade, people, enrollments, snapshot):
    if batch.errors or not batch.rows:
        raise ValueError('\n'.join(batch.errors) or '전체 명단을 업로드하세요.')
    if not 1900 <= base_year < 9999:
        raise ValueError('기준 학년도는 1900~9998 사이여야 합니다.')
    if batch.kind == 'students' and max_grade not in (3, 6):
        raise ValueError('Wee센터에서는 학생 자동 진급을 제공하지 않습니다.')
    draft = YearDraft(batch.kind, base_year, max_grade, people, enrollments, [], snapshot)
    names = defaultdict(list)
    for pid, person in people.items():
        names[person['name']].append(pid)
    for imported in batch.rows:
        value = imported.value.model_dump(mode='json')
        candidates = []
        for pid in names[value['name']]:
            if batch.kind == 'teachers':
                candidates.append(pid)
                continue
            target = enrollments.get((pid, base_year + 1))
            base = enrollments.get((pid, base_year))
            if (target and target['grade'] == value['grade']) or (base and base['status'] == '재학'
                    and value['grade'] >= 2 and base['grade'] == value['grade'] - 1):
                candidates.append(pid)
        draft.rows.append(DraftRow(f'file:{imported.number}', value, candidates=tuple(candidates), confirmed=not candidates))
    counts = Counter(pid for row in draft.rows for pid in row.candidates)
    if batch.kind == 'students':
        for row in draft.rows:
            if len(row.candidates) == 1 and counts[row.candidates[0]] == 1:
                row.person_id, row.confirmed = row.candidates[0], True
    else:
        # 빈 연락처와 중복 연락처는 동일인을 확정할 근거가 되지 않는다.
        contacts = defaultdict(list)
        for pid, person in people.items():
            contact = (person.get('contact') or '').strip()
            if contact:
                contacts[contact].append(pid)
        imported_contacts = Counter((row.source.get('contact') or '').strip() for row in draft.rows)
        for row in draft.rows:
            contact = (row.source.get('contact') or '').strip()
            matches = contacts.get(contact, [])
            if matches:
                row.candidates = tuple(dict.fromkeys([*matches, *row.candidates]))
                row.confirmed = False
            if len(matches) == 1 and imported_contacts[contact] == 1:
                row.person_id, row.confirmed = matches[0], True
    return draft
