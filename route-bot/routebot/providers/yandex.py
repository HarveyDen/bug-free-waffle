"""Маршруты через Яндекс Карты (Геокодер API + Маршрутизатор v2)."""

from __future__ import annotations

import aiohttp

from ..models import RouteError, RouteResult
from ..utils import Point
from .base import BaseProvider

_GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"
_ROUTER_URL = "https://api.routing.yandex.net/v2/route"


class YandexMapsProvider(BaseProvider):
    name = "Яндекс Карты"

    def __init__(
        self, geocoder_key: str, router_key: str, session: aiohttp.ClientSession
    ) -> None:
        super().__init__(session)
        self._geocoder_key = geocoder_key
        self._router_key = router_key

    async def build_route(self, origin: str, destination: str) -> RouteResult:
        a_point, a_name = await self._geocode(origin)
        b_point, b_name = await self._geocode(destination)

        params = {
            "apikey": self._router_key,
            "waypoints": f"{a_point[0]},{a_point[1]}|{b_point[0]},{b_point[1]}",
            "mode": "driving",
        }
        async with self._session.get(_ROUTER_URL, params=params) as resp:
            if resp.status == 403:
                raise RouteError(
                    "Яндекс Маршрутизатор отклонил ключ API (403). "
                    "Проверьте YANDEX_ROUTER_API_KEY и подключённый тариф."
                )
            if resp.status != 200:
                raise RouteError(f"Ошибка Яндекс Маршрутизатора: HTTP {resp.status}.")
            data = await resp.json()

        legs = data.get("route", {}).get("legs", [])
        steps = [step for leg in legs for step in leg.get("steps", [])]
        if not steps or any(leg.get("status") == "FAIL" for leg in legs):
            raise RouteError("Яндекс Карты не нашли автомобильный маршрут между этими точками.")

        distance_m = sum(step.get("length", 0) for step in steps)
        duration_s = sum(step.get("duration", 0) for step in steps)
        points: list[Point] = [
            (lat, lon)
            for step in steps
            for lat, lon in step.get("polyline", {}).get("points", [])
        ]

        cities = await self._cities_along(points, self._reverse_city)

        map_url = (
            "https://yandex.ru/maps/?rtext="
            f"{a_point[0]},{a_point[1]}~{b_point[0]},{b_point[1]}&rtt=auto"
        )
        return RouteResult(
            provider=self.name,
            origin=a_name,
            destination=b_name,
            distance_km=distance_m / 1000,
            duration_min=duration_s / 60 if duration_s else None,
            cities=cities,
            map_url=map_url,
        )

    async def _geocode(self, query: str) -> tuple[Point, str]:
        """Название места -> ((lat, lon), распознанное имя)."""
        data = await self._geocoder_request(geocode=query)
        members = data["response"]["GeoObjectCollection"]["featureMember"]
        if not members:
            raise RouteError(f"Яндекс Карты не нашли место «{query}».")
        obj = members[0]["GeoObject"]
        lon, lat = map(float, obj["Point"]["pos"].split())
        return (lat, lon), obj.get("name", query)

    async def _reverse_city(self, point: Point) -> str | None:
        """Название населённого пункта по координатам (kind=locality)."""
        data = await self._geocoder_request(
            geocode=f"{point[1]},{point[0]}", kind="locality", results="1"
        )
        members = data["response"]["GeoObjectCollection"]["featureMember"]
        if not members:
            return None
        return members[0]["GeoObject"].get("name")

    async def _geocoder_request(self, **params: str) -> dict:
        query = {
            "apikey": self._geocoder_key,
            "format": "json",
            "lang": "ru_RU",
            **params,
        }
        async with self._session.get(_GEOCODER_URL, params=query) as resp:
            if resp.status == 403:
                raise RouteError(
                    "Яндекс Геокодер отклонил ключ API (403). "
                    "Проверьте YANDEX_GEOCODER_API_KEY."
                )
            if resp.status != 200:
                raise RouteError(f"Ошибка Яндекс Геокодера: HTTP {resp.status}.")
            return await resp.json()
