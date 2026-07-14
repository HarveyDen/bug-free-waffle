"""Telegram-бот: маршруты от точки А до точки Б через Google Maps и Яндекс Карты.

Запуск:  python bot.py  (токены берутся из .env, см. .env.example)
"""

from __future__ import annotations

import asyncio
import html
import logging

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from routebot.config import Config, load_config
from routebot.models import RouteError, RouteResult
from routebot.providers import GoogleMapsProvider, YandexMapsProvider
from routebot.utils import format_duration, parse_route_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("routebot")

dp = Dispatcher()

# Последний распознанный запрос "А - Б" для каждого чата: chat_id -> (origin, destination)
_pending: dict[int, tuple[str, str]] = {}

HELP_TEXT = (
    "Я строю автомобильные маршруты от точки А до точки Б и показываю, "
    "через какие города они проходят, а также расстояние в километрах.\n\n"
    "Просто отправьте две точки через дефис или стрелку, например:\n"
    "<code>Алматы - Астана</code>\n"
    "<code>Москва → Санкт-Петербург</code>\n\n"
    "Или командой: <code>/route Алматы - Астана</code>\n\n"
    "Затем выберите карты: Google, Яндекс или обе сразу."
)


def _provider_keyboard(cfg: Config) -> InlineKeyboardMarkup:
    row = []
    if cfg.google_enabled:
        row.append(InlineKeyboardButton(text="🌍 Google", callback_data="prov:google"))
    if cfg.yandex_enabled:
        row.append(InlineKeyboardButton(text="🗺 Яндекс", callback_data="prov:yandex"))
    rows = [row]
    if cfg.google_enabled and cfg.yandex_enabled:
        rows.append([InlineKeyboardButton(text="⚖️ Сравнить обе", callback_data="prov:both")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_result(r: RouteResult) -> str:
    lines = [
        f"<b>{html.escape(r.provider)}</b>",
        f"🚗 {html.escape(r.origin)} → {html.escape(r.destination)}",
        f"📏 Расстояние: <b>{r.distance_km:.0f} км</b>",
    ]
    duration = format_duration(r.duration_min)
    if duration:
        lines.append(f"⏱ В пути: ~{duration}")
    if r.cities:
        chain = " → ".join(html.escape(c) for c in r.cities)
        lines.append(f"🏙 Через населённые пункты:\n{chain}")
    if r.map_url:
        lines.append(f'🔗 <a href="{r.map_url}">Открыть маршрут на карте</a>')
    return "\n".join(lines)


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer("Привет! 👋\n\n" + HELP_TEXT)


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@dp.message(F.text)
async def on_text(message: Message, cfg: Config) -> None:
    parsed = parse_route_query(message.text or "")
    if not parsed:
        await message.answer(
            "Не понял точки маршрута. 🤔\n"
            "Отправьте их в формате: <code>Алматы - Астана</code>"
        )
        return
    if not (cfg.google_enabled or cfg.yandex_enabled):
        await message.answer(
            "Ни один картографический сервис не настроен. "
            "Добавьте GOOGLE_MAPS_API_KEY и/или ключи Яндекса в .env."
        )
        return
    origin, destination = parsed
    _pending[message.chat.id] = parsed
    await message.answer(
        f"Маршрут: <b>{html.escape(origin)}</b> → <b>{html.escape(destination)}</b>\n"
        "Какими картами построить?",
        reply_markup=_provider_keyboard(cfg),
    )


@dp.callback_query(F.data.startswith("prov:"))
async def on_provider_chosen(
    query: CallbackQuery, cfg: Config, session: aiohttp.ClientSession
) -> None:
    pending = _pending.get(query.message.chat.id) if query.message else None
    if not pending:
        await query.answer("Запрос устарел, отправьте маршрут ещё раз.", show_alert=True)
        return
    origin, destination = pending
    choice = (query.data or "").removeprefix("prov:")

    providers = []
    if choice in ("google", "both") and cfg.google_enabled:
        providers.append(GoogleMapsProvider(cfg.google_api_key, session))
    if choice in ("yandex", "both") and cfg.yandex_enabled:
        providers.append(YandexMapsProvider(cfg.yandex_geocoder_key, cfg.yandex_router_key, session))
    if not providers:
        await query.answer("Этот сервис не настроен.", show_alert=True)
        return

    await query.answer()
    status = await query.message.answer("⏳ Строю маршрут, это может занять до минуты...")

    async def build(provider) -> str:
        try:
            return format_result(await provider.build_route(origin, destination))
        except RouteError as e:
            return f"<b>{html.escape(provider.name)}</b>\n⚠️ {html.escape(str(e))}"
        except Exception:
            log.exception("Route failed (%s): %s -> %s", provider.name, origin, destination)
            return (
                f"<b>{html.escape(provider.name)}</b>\n"
                "⚠️ Не удалось построить маршрут: внутренняя ошибка сервиса."
            )

    results = await asyncio.gather(*(build(p) for p in providers))
    await status.edit_text(
        "\n\n➖➖➖➖➖\n\n".join(results),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def main() -> None:
    cfg = load_config()
    if not cfg.google_enabled:
        log.warning("GOOGLE_MAPS_API_KEY не задан — маршруты Google отключены.")
    if not cfg.yandex_enabled:
        log.warning("Ключи Яндекса не заданы — маршруты Яндекс отключены.")

    bot = Bot(cfg.telegram_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    async with aiohttp.ClientSession() as session:
        # cfg и session прокидываются во все хэндлеры через DI aiogram
        await dp.start_polling(bot, cfg=cfg, session=session)


if __name__ == "__main__":
    asyncio.run(main())
