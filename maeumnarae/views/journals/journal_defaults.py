"""새 일지 작성 시 현재 학교 설정에 맞는 기본 운영시간을 사용한다."""

from maeumnarae.core.database import Database
from maeumnarae.repositories.settings.school_settings_repo import SchoolSettingsRepository


def default_duration_minutes(database: Database, *, fallback: int) -> int:
    school_level = SchoolSettingsRepository(database).get().school_level
    return {'초등학교': 40, '중학교': 45, '고등학교': 50}.get(school_level, fallback)
