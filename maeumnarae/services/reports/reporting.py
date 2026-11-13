"""한국 날짜 범위와 상담 상태 표시. UI·DB에 의존하지 않는 순수 함수."""

from datetime import date, datetime, time, timedelta, timezone


KST = timezone(timedelta(hours=9))
STATUS_LABELS = {'scheduled': '예약', 'completed': '완료', 'cancelled': '취소'}


def date_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """양 끝 날짜를 포함하는 KST 구간을 [시작, 다음 날) datetime으로 변환한다."""
    if start > end:
        raise ValueError('종료일은 시작일보다 빠를 수 없습니다.')
    if end == date.max:
        raise ValueError('종료일은 9999-12-30 이전 날짜를 선택하세요.')
    return datetime.combine(start, time.min, KST), datetime.combine(end + timedelta(days=1), time.min, KST)
