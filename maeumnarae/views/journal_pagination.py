"""일지 목록의 페이지 크기와 전체 페이지 계산."""

PAGE_SIZE = 10


def load_page(list_records, count_records, offset, *args, **kwargs):
    total = count_records(*args, **kwargs)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    offset = min(max(0, offset), (pages - 1) * PAGE_SIZE)
    entries = list_records(*args, limit=PAGE_SIZE, offset=offset, **kwargs)
    return entries, offset, pages
