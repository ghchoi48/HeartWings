"""일지 페이지 경계와 저장소별 전체 건수 조회 검증."""
from unittest.mock import Mock

import pytest

from maeumnarae.core.database import Database
from maeumnarae.repositories.counseling_repo import CounselingRepository
from maeumnarae.repositories.special_education_repo import SpecialEducationLogRepository
from maeumnarae.repositories.group_counseling_repo import GroupCounselingRepository
from maeumnarae.repositories.consultation_repo import ConsultationRepository
from maeumnarae.repositories.psychological_test_repo import PsychologicalTestRepository
from maeumnarae.views.journal_pagination import load_page


@pytest.mark.parametrize('total,offset,expected_offset,pages,length', [
    (0, 0, 0, 1, 0), (10, 0, 0, 1, 10), (11, 0, 0, 2, 10),
    (11, 10, 10, 2, 1), (21, 20, 20, 3, 1), (10, 20, 0, 1, 10),
])
def test_page_boundaries(total, offset, expected_offset, pages, length):
    records = list(range(total))
    listing = Mock(side_effect=lambda student_id, limit, offset: records[offset:offset + limit])
    count = Mock(return_value=total)
    entries, actual_offset, actual_pages = load_page(listing, count, offset, student_id=7)
    assert (actual_offset, actual_pages, len(entries)) == (expected_offset, pages, length)
    count.assert_called_once_with(student_id=7)
    listing.assert_called_once_with(student_id=7, limit=10, offset=expected_offset)


@pytest.mark.parametrize('repository,method,args,kwargs', [
    (CounselingRepository, 'count', (), dict(student_id=1, case_id=1)),
    (SpecialEducationLogRepository, 'count', (), dict(student_id=1, case_id=1)),
    (GroupCounselingRepository, 'count_logs', (1,), {}),
    (ConsultationRepository, 'count', (1,), {}),
    (PsychologicalTestRepository, 'count', (1,), {}),
])
def test_empty_repository_count(tmp_path, repository, method, args, kwargs):
    db = Database('test-only', tmp_path / 'counts.db')
    db.initialize()
    assert getattr(repository(db), method)(*args, **kwargs) == 0
