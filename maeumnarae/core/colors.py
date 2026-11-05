"""Shared hex color and contrast helpers."""

import re


# Prefer white until black offers more than twice its contrast.
WHITE_TEXT_PREFERENCE_RATIO = 2.0


def normalize_color(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if re.fullmatch(r'#[0-9a-f]{3}', value):
        value = '#' + ''.join(channel * 2 for channel in value[1:])
    return value if re.fullmatch(r'#[0-9a-f]{6}', value) else None


def luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrasting_text_color(color: str) -> str:
    """Prefer white for comparable contrast; use black on lighter backgrounds."""
    normalized = normalize_color(color)
    if normalized is None:
        raise ValueError(f'Invalid hex color: {color!r}')
    brightness = luminance(normalized)
    black_contrast = (brightness + 0.05) / 0.05
    white_contrast = 1.05 / (brightness + 0.05)
    return '#000000' if black_contrast > white_contrast * WHITE_TEXT_PREFERENCE_RATIO else '#ffffff'


def readable_accent(color: str, background: str) -> str:
    """배경 없는 강조 글씨는 화면 배경과 4.5:1 이상의 대비를 확보한다."""
    target = 0 if luminance(background) > 0.5 else 255
    channels = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    for step in range(101):
        candidate = '#' + ''.join(f'{round(c + (target - c) * step / 100):02x}' for c in channels)
        low, high = sorted((luminance(candidate), luminance(background)))
        if (high + 0.05) / (low + 0.05) >= 4.5:
            return candidate
    return candidate

