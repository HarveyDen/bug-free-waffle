"""Общие типы данных и ошибки."""

from __future__ import annotations

from dataclasses import dataclass, field


class RouteError(Exception):
    """Ошибка построения маршрута с человекочитаемым сообщением."""


@dataclass
class RouteResult:
    provider: str  # человекочитаемое имя картографического сервиса
    origin: str  # распознанное название точки А
    destination: str  # распознанное название точки Б
    distance_km: float
    duration_min: float | None
    cities: list[str] = field(default_factory=list)  # населённые пункты по пути
    map_url: str | None = None  # ссылка на маршрут на сайте карт
