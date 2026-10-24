"""저장소 내부의 날짜 직렬화와 페이지 검증."""

from datetime import datetime, timezone

from pydantic import BaseModel


def utc_text(value: datetime) -> str:
    """정렬/기간 조회가 가능한 고정 길이 UTC 문자열로 변환한다."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('시간대가 포함된 시각이 필요합니다.')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


def now_text() -> str:
    """현재 UTC 시각을 반환한다."""
    return utc_text(datetime.now(timezone.utc))


def values(model: BaseModel) -> dict:
    """날짜와 시각을 SQLite가 저장할 수 있는 값으로 바꾼다."""
    result = model.model_dump(mode='json')
    if 'starts_at' in result:
        result['starts_at'] = utc_text(model.starts_at)
    return result


def check_page(limit: int, offset: int) -> None:
    """실수로 전체 상담 내용을 메모리에 적재하는 것을 방지한다."""
    if not 1 <= limit <= 1000 or offset < 0:
        raise ValueError('limit은 1~1000, offset은 0 이상이어야 합니다.')
