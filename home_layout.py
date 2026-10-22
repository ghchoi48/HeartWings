"""홈의 24열, 세로 10px 격자와 기존 배치 변환."""

from copy import deepcopy
from math import ceil

COLUMNS = 24
MIN_HEIGHT = 160
MAX_HEIGHT = 1600
DEFAULT_SIZES = {
    'clock': (8, 290), 'todo': (8, 390), 'teacher_search': (8, 390),
    'meal': (8, 520), 'memo': (8, 430),
}


def overlaps(a, b):
    return (a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width']
            and a['y'] < b['y'] + ceil(b['height'] / 10) + 1
            and b['y'] < a['y'] + ceil(a['height'] / 10) + 1)


def arrange(layout, priority=None):
    """빈 위치를 채우고, 조작한 위젯과 겹치는 위젯을 아래로 옮긴다."""
    result = deepcopy(layout)
    placed = []
    ordered = sorted(result, key=lambda item: item['id'] != priority) if priority else result
    for item in ordered:
        item.setdefault('width', item.get('span', 1) * 8)
        item.setdefault('height', 290)
        if 'x' not in item or 'y' not in item:
            item['y'] = 0
            while True:
                for x in range(COLUMNS - item['width'] + 1):
                    item['x'] = x
                    if not any(overlaps(item, other) for other in placed):
                        break
                else:
                    item['y'] += 1
                    continue
                break
        item['x'] = min(item['x'], COLUMNS - item['width'])
        while any(overlaps(item, other) for other in placed):
            item['y'] = max(other['y'] + ceil(other['height'] / 10) + 1
                            for other in placed if overlaps(item, other))
        placed.append(item)
    return result
