"""Тесты для routebot.utils (не требуют сети и API-ключей)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routebot.utils import (
    decode_google_polyline,
    dedupe_keep_order,
    format_duration,
    haversine_km,
    parse_route_query,
    sample_route_points,
)


def test_parse_simple_dash():
    assert parse_route_query("Алматы - Астана") == ("Алматы", "Астана")


def test_parse_em_dash_and_arrow():
    assert parse_route_query("Москва — Санкт-Петербург") == ("Москва", "Санкт-Петербург")
    assert parse_route_query("Алматы -> Шымкент") == ("Алматы", "Шымкент")
    assert parse_route_query("Алматы → Тараз") == ("Алматы", "Тараз")


def test_parse_keeps_hyphenated_city_names():
    assert parse_route_query("Усть-Каменогорск - Семей") == ("Усть-Каменогорск", "Семей")


def test_parse_route_command():
    assert parse_route_query("/route Алматы - Астана") == ("Алматы", "Астана")
    assert parse_route_query("/route@MyBot Алматы - Астана") == ("Алматы", "Астана")


def test_parse_newline_separator():
    assert parse_route_query("Алматы\nАстана") == ("Алматы", "Астана")


def test_parse_rejects_garbage():
    assert parse_route_query("просто текст") is None
    assert parse_route_query("А - Б - В") is None
    assert parse_route_query("") is None


def test_haversine_known_distance():
    almaty = (43.238949, 76.889709)
    astana = (51.169392, 71.449074)
    d = haversine_km(almaty, astana)
    assert 950 < d < 1000  # ~970 км по прямой


def test_decode_google_polyline_reference():
    # Пример из документации Google
    points = decode_google_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert points == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_sample_route_points_limits_count():
    # Прямая линия длиной ~500 км из 1000 точек
    points = [(50.0 + i * 0.005, 60.0) for i in range(1000)]
    samples = sample_route_points(points, step_km=25.0, max_samples=30)
    assert 2 <= len(samples) <= 31
    assert samples[0] == points[0]
    assert samples[-1] == points[-1]


def test_sample_route_points_short_route():
    points = [(50.0, 60.0), (50.01, 60.0)]
    samples = sample_route_points(points)
    assert samples[0] == points[0] and samples[-1] == points[-1]
    assert sample_route_points([]) == []


def test_dedupe_keep_order():
    assert dedupe_keep_order(["Алматы", None, "Капшагай", "алматы", "Астана", "Капшагай"]) == [
        "Алматы",
        "Капшагай",
        "Астана",
    ]


def test_format_duration():
    assert format_duration(None) is None
    assert format_duration(45) == "45 мин"
    assert format_duration(60) == "1 ч"
    assert format_duration(79) == "1 ч 19 мин"
    assert format_duration(920) == "15 ч 20 мин"
