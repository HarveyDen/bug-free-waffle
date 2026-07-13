"""Вспомогательные функции: разбор запроса, работа с геометрией маршрута.

Модуль не зависит от aiogram/aiohttp, чтобы его можно было тестировать отдельно.
"""

from __future__ import annotations

import math
import re

Point = tuple[float, float]  # (lat, lon)

# Разделители точек А и Б: " - ", "—", "->", "→", ";", перевод строки.
# Дефис учитывается только с пробелами вокруг, чтобы не резать названия
# вроде "Усть-Каменогорск".
_SEPARATORS = re.compile(r"\s+[-—–]\s+|\s*(?:->|→|=>|;)\s*|\n+")


def parse_route_query(text: str) -> tuple[str, str] | None:
    """Разбирает "Алматы - Астана" на пару (origin, destination).

    Возвращает None, если распознать две точки не удалось.
    """
    text = text.strip()
    if text.startswith("/"):
        # убираем "/route" или "/route@BotName"
        text = re.sub(r"^/\w+(@\w+)?\s*", "", text)
    parts = [p.strip() for p in _SEPARATORS.split(text) if p and p.strip()]
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def haversine_km(a: Point, b: Point) -> float:
    """Расстояние по прямой между двумя точками в километрах."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def decode_google_polyline(encoded: str) -> list[Point]:
    """Декодирует Google Encoded Polyline в список (lat, lon)."""
    points: list[Point] = []
    index = lat = lon = 0
    while index < len(encoded):
        for is_lon in (False, True):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lon:
                lon += delta
            else:
                lat += delta
        points.append((lat / 1e5, lon / 1e5))
    return points


def sample_route_points(
    points: list[Point], step_km: float = 25.0, max_samples: int = 30
) -> list[Point]:
    """Выбирает точки вдоль маршрута примерно каждые step_km километров.

    Количество точек ограничено max_samples, чтобы не сжигать квоту
    обратного геокодирования на длинных маршрутах.
    """
    if not points:
        return []
    if len(points) == 1:
        return list(points)

    total = 0.0
    for prev, cur in zip(points, points[1:]):
        total += haversine_km(prev, cur)
    step = max(step_km, total / max(max_samples - 1, 1))

    samples = [points[0]]
    acc = 0.0
    for prev, cur in zip(points, points[1:]):
        acc += haversine_km(prev, cur)
        if acc >= step:
            samples.append(cur)
            acc = 0.0
    if samples[-1] != points[-1]:
        samples.append(points[-1])
    return samples


def dedupe_keep_order(names: list[str | None]) -> list[str]:
    """Убирает пустые значения и повторы, сохраняя порядок следования."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def format_duration(minutes: float | None) -> str | None:
    """78.5 -> "1 ч 19 мин"."""
    if minutes is None:
        return None
    total = int(round(minutes))
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours} ч {mins} мин"
    if hours:
        return f"{hours} ч"
    return f"{mins} мин"
