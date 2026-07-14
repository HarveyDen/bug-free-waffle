"""Общий код провайдеров карт."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Awaitable, Callable

import aiohttp

from ..models import RouteResult
from ..utils import Point, dedupe_keep_order, sample_route_points

# Сколько обратных геокодирований выполняем одновременно
_GEOCODE_CONCURRENCY = 5


class BaseProvider(ABC):
    """Провайдер карт: геокодирование, маршрут, города вдоль маршрута."""

    name: str = "?"

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    @abstractmethod
    async def build_route(self, origin: str, destination: str) -> RouteResult:
        """Строит маршрут и возвращает результат с городами по пути."""

    async def _cities_along(
        self,
        points: list[Point],
        reverse_geocode: Callable[[Point], Awaitable[str | None]],
        step_km: float = 25.0,
    ) -> list[str]:
        """Сэмплирует геометрию маршрута и возвращает населённые пункты по пути."""
        samples = sample_route_points(points, step_km=step_km)
        sem = asyncio.Semaphore(_GEOCODE_CONCURRENCY)

        async def one(pt: Point) -> str | None:
            async with sem:
                try:
                    return await reverse_geocode(pt)
                except Exception:
                    # Один неудавшийся геокод не должен ронять весь маршрут
                    return None

        names = await asyncio.gather(*(one(p) for p in samples))
        return dedupe_keep_order(list(names))
