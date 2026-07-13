"""Конфигурация из переменных окружения / файла .env."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    telegram_token: str
    google_api_key: str | None
    yandex_geocoder_key: str | None
    yandex_router_key: str | None

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_api_key)

    @property
    def yandex_enabled(self) -> bool:
        return bool(self.yandex_geocoder_key and self.yandex_router_key)


def load_config() -> Config:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Не задан TELEGRAM_BOT_TOKEN. Создайте бота через @BotFather "
            "и укажите токен в .env (см. .env.example)."
        )
    return Config(
        telegram_token=token,
        google_api_key=os.getenv("GOOGLE_MAPS_API_KEY", "").strip() or None,
        yandex_geocoder_key=os.getenv("YANDEX_GEOCODER_API_KEY", "").strip() or None,
        yandex_router_key=os.getenv("YANDEX_ROUTER_API_KEY", "").strip() or None,
    )
