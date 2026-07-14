"""Маршруты через Google Maps (Directions API + Geocoding API)."""

from __future__ import annotations

from urllib.parse import quote_plus

import aiohttp

from ..models import RouteError, RouteResult
from ..utils import Point, decode_google_polyline
from .base import BaseProvider

_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Типы address_components, которые считаем населённым пунктом
_LOCALITY_TYPES = ("locality", "postal_town")


class GoogleMapsProvider(BaseProvider):
    name = "Google Maps"

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        super().__init__(session)
        self._key = api_key

    async def build_route(self, origin: str, destination: str) -> RouteResult:
        params = {
            "origin": origin,
            "destination": destination,
            "mode": "driving",
            "language": "ru",
            "key": self._key,
        }
        async with self._session.get(_DIRECTIONS_URL, params=params) as resp:
            data = await resp.json()

        status = data.get("status")
        if status == "NOT_FOUND":
            raise RouteError("Google Maps не смог распознать одну из точек маршрута.")
        if status == "ZERO_RESULTS":
            raise RouteError("Google Maps не нашёл автомобильный маршрут между этими точками.")
        if status != "OK":
            raise RouteError(
                f"Ошибка Google Maps: {status}. {data.get('error_message', '')}".strip()
            )

        route = data["routes"][0]
        legs = route["legs"]
        distance_m = sum(leg["distance"]["value"] for leg in legs)
        duration_s = sum(leg["duration"]["value"] for leg in legs)
        points = decode_google_polyline(route["overview_polyline"]["points"])

        cities = await self._cities_along(points, self._reverse_city)

        map_url = (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={quote_plus(origin)}&destination={quote_plus(destination)}"
            "&travelmode=driving"
        )
        return RouteResult(
            provider=self.name,
            origin=legs[0].get("start_address", origin),
            destination=legs[-1].get("end_address", destination),
            distance_km=distance_m / 1000,
            duration_min=duration_s / 60,
            cities=cities,
            map_url=map_url,
        )

    async def _reverse_city(self, point: Point) -> str | None:
        """Название населённого пункта по координатам (или None вне населённых пунктов)."""
        params = {
            "latlng": f"{point[0]},{point[1]}",
            "result_type": "|".join(_LOCALITY_TYPES),
            "language": "ru",
            "key": self._key,
        }
        async with self._session.get(_GEOCODE_URL, params=params) as resp:
            data = await resp.json()
        if data.get("status") != "OK":
            return None
        for result in data.get("results", []):
            for component in result.get("address_components", []):
                if any(t in component.get("types", []) for t in _LOCALITY_TYPES):
                    return component.get("long_name")
        return None
