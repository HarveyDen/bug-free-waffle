#!/usr/bin/env python3
"""Массовая выгрузка PDF-заявлений с портала elicense.kz.

Скрипт открывает Chrome (через Playwright), по очереди заходит под каждым
сохранённым профилем-логином, обходит список "Мои заявления"
(/LicensingContent/SimpleSearchRequest) постранично и скачивает по каждому
заявлению PDF-файл в одну общую папку "Заявления" на рабочем столе.
Ничего не сортируется по подпапкам — все файлы складываются в один каталог.

Вход в портал (ЭЦП/NCALayer) выполняется вручную один раз на профиль:
скрипт открывает окно браузера и ждёт, пока вы авторизуетесь. Cookie
сохраняются в каталоге профиля, дальше запуски идут без ручного входа.

Типовые команды:

    # 1. Один раз завести профили и войти в них руками
    python3 download_zayavleniya.py setup ivan petr sultan

    # 2. Скачать всё по всем профилям
    python3 download_zayavleniya.py run

    # 3. Держать выгрузку в актуальном состоянии (проверка каждые 30 минут)
    python3 download_zayavleniya.py run --watch 30

    # Прочее
    python3 download_zayavleniya.py list                # какие профили заведены
    python3 download_zayavleniya.py run -p ivan --since 01.08.2026
    python3 download_zayavleniya.py run --pages 1-20 --full-scan

Зависимости:  pip install playwright  &&  playwright install chromium
(если в системе стоит обычный Chrome, он и будет использован).
"""

import argparse
import csv
import datetime as dt
import json
import os
import platform
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

# Адрес портала. Переопределяется переменной ELICENSE_BASE_URL (нужно для
# тестового стенда, в обычной работе трогать не надо).
BASE_URL = os.environ.get("ELICENSE_BASE_URL", "https://elicense.kz").rstrip("/")
LIST_URL = BASE_URL + "/LicensingContent/SimpleSearchRequest"
PENDING_URL = BASE_URL + "/LicensingContent/SimpleSearchPendingRequest"

# Каталог со служебными данными: профили Chrome, состояние выгрузки, лог.
# Специально держим его ОТДЕЛЬНО от папки "Заявления", чтобы в неё попадали
# только сами PDF-файлы.
HOME_DIR = Path.home() / ".elicense_downloader"
PROFILES_DIR = HOME_DIR / "profiles"
STATE_FILE = HOME_DIR / "state.json"
INDEX_CSV = HOME_DIR / "index.csv"
LOG_FILE = HOME_DIR / "log.txt"

# Источники PDF по заявлению. Пробуем по порядку, берём первый удавшийся.
# df  — форма сведений (именно так выглядит образец Request_KZ..._df.pdf)
# req — файл заявления из /Requests/GetFileListByRequest
# page— печатная версия страницы заявления
SOURCE_KEYS = ("df", "req", "page")

DEFAULT_DELAY = 1.2          # пауза между скачиваниями, сек
DEFAULT_STOP_AFTER_KNOWN = 30  # сколько подряд уже скачанных заявлений — и хватит
LOGIN_WAIT_SECONDS = 600     # сколько ждать ручной авторизации


# --------------------------------------------------------------------------
# Утилиты: пути, лог, состояние
# --------------------------------------------------------------------------

def log(msg, quiet=False):
    """Печать в консоль + дозапись в лог-файл."""
    line = "[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg)
    if not quiet:
        print(line, flush=True)
    try:
        HOME_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (dt.datetime.now().isoformat(timespec="seconds"), msg))
    except OSError:
        pass


def desktop_dir():
    """Путь к рабочему столу с учётом Windows/OneDrive и локализованных имён."""
    system = platform.system()

    if system == "Windows":
        # Официальный способ: спросить у Windows, где Desktop (учитывает
        # перенос рабочего стола в OneDrive и нерусскую/русскую локаль).
        try:
            import ctypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", ctypes.c_ulong),
                            ("Data2", ctypes.c_ushort),
                            ("Data3", ctypes.c_ushort),
                            ("Data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
            folderid = GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                            (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41))
            path_ptr = ctypes.c_wchar_p()
            res = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(folderid), 0, None, ctypes.byref(path_ptr))
            if res == 0 and path_ptr.value:
                p = Path(path_ptr.value)
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                if p.is_dir():
                    return p
        except Exception:
            pass
        up = os.environ.get("USERPROFILE")
        if up:
            for name in ("Desktop", "Рабочий стол"):
                p = Path(up) / name
                if p.is_dir():
                    return p
            return Path(up) / "Desktop"

    if system == "Linux":
        # xdg-user-dir знает про локализованные имена ("Рабочий стол")
        try:
            import subprocess
            out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                                 text=True, timeout=5)
            p = Path(out.stdout.strip())
            if out.returncode == 0 and str(p) and p.is_dir():
                return p
        except Exception:
            pass

    for name in ("Desktop", "Рабочий стол"):
        p = Path.home() / name
        if p.is_dir():
            return p
    return Path.home() / "Desktop"


def target_dir(custom=None):
    """Папка, куда складываем PDF: <Рабочий стол>/Заявления."""
    out = Path(custom).expanduser() if custom else desktop_dir() / "Заявления"
    out.mkdir(parents=True, exist_ok=True)
    return out


def load_state():
    if STATE_FILE.exists():
        try:
            with STATE_FILE.open(encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            log("Файл состояния повреждён, начинаем с чистого листа")
    return {"profiles": {}}


def save_state(state):
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    tmp.replace(STATE_FILE)


def profile_state(state, profile):
    return state["profiles"].setdefault(profile, {})


def existing_copy(state, number, out_dir):
    """Уже скачанный файл по номеру заявления — среди ВСЕХ профилей.

    Нужно по двум причинам: одно заявление может быть видно из нескольких
    логинов (не плодим дубли), а удалённый из папки файл должен скачаться
    заново при следующем проходе.
    """
    for pname, items in state.get("profiles", {}).items():
        rec = items.get(number)
        if rec and rec.get("ok") and rec.get("file") and (out_dir / rec["file"]).exists():
            return pname, rec["file"]
    return None, None


def append_index(row):
    """Реестр скачанного (CSV лежит рядом с состоянием, не в папке заявлений)."""
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    new = not INDEX_CSV.exists()
    with INDEX_CSV.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new:
            w.writerow(["Профиль", "Номер заявления", "ID", "Дата создания",
                        "Статус", "Вид деятельности", "Файл", "Скачано"])
        w.writerow(row)


BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name):
    name = BAD_CHARS.sub("_", (name or "").strip()).strip(". ")
    return name[:150] or "request.pdf"


def unique_path(folder, filename):
    """Не перезаписываем чужие файлы: при совпадении имени добавляем _2, _3..."""
    p = folder / filename
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    for i in range(2, 1000):
        cand = folder / ("%s_%d%s" % (stem, i, suffix))
        if not cand.exists():
            return cand
    return folder / ("%s_%s%s" % (stem, int(time.time()), suffix))


def filename_from_cd(cd):
    """Имя файла из заголовка Content-Disposition."""
    if not cd:
        return None
    m = re.search(r"filename\*\s*=\s*[\w-]+''([^;]+)", cd, re.I)
    if m:
        try:
            return unquote(m.group(1)).strip().strip('"')
        except Exception:
            pass
    m = re.search(r'filename\s*=\s*"([^"]+)"', cd, re.I) or \
        re.search(r'filename\s*=\s*([^;]+)', cd, re.I)
    if m:
        return m.group(1).strip().strip('"')
    return None


def parse_date(text):
    """'31.08.2026 12:43:43' / '31.08.2026' / '2026-08-31' -> date."""
    text = (text or "").strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# Работа с браузером
# --------------------------------------------------------------------------

def profile_dir(name, base=None):
    return (Path(base).expanduser() if base else PROFILES_DIR) / name


def known_profiles(base=None):
    root = Path(base).expanduser() if base else PROFILES_DIR
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def launch_context(pw, args, profile=None):
    """Запуск Chrome с постоянным профилем (cookie переживают перезапуск)."""
    if args.user_data_dir:                      # режим "родной профиль Chrome"
        udd = Path(args.user_data_dir).expanduser()
        extra = ["--profile-directory=%s" % args.profile_directory] if args.profile_directory else []
    else:
        udd = profile_dir(profile, args.profiles_dir)
        extra = []
    udd.mkdir(parents=True, exist_ok=True)

    browser_args = ["--disable-blink-features=AutomationControlled",
                    "--no-first-run", "--no-default-browser-check"] + extra
    if getattr(args, "no_sandbox", False):
        browser_args.append("--no-sandbox")

    launch_args = dict(
        user_data_dir=str(udd),
        headless=bool(getattr(args, "headless", False)),
        accept_downloads=True,
        viewport={"width": 1440, "height": 900},
        args=browser_args,
    )
    if getattr(args, "chrome_path", None):
        return pw.chromium.launch_persistent_context(
            executable_path=args.chrome_path, **launch_args)
    try:
        return pw.chromium.launch_persistent_context(channel="chrome", **launch_args)
    except Exception as exc:
        log("Обычный Chrome не запустился (%s), пробуем встроенный Chromium" %
            str(exc).splitlines()[0][:120])
        return pw.chromium.launch_persistent_context(**launch_args)


def is_authenticated(page):
    """Признак входа: на странице есть меню профиля и таблица заявлений."""
    try:
        if "/Account/LogOn" in page.url or "/Account/Login" in page.url:
            return False
        return bool(page.query_selector("#mainFIOdropbtn") or
                    page.query_selector("#table__content__body"))
    except Exception:
        return False


def session_alive(api):
    """Тихая проверка сессии запросом в фоне — вкладку пользователя не трогаем.

    Это важно: пока человек вводит пароль или подписывает ЭЦП через NCALayer,
    перезагружать его страницу нельзя — вход собьётся.
    """
    try:
        resp = api.get(LIST_URL, timeout=30000)
        if not resp.ok:
            return False
        html = resp.text()
        return "table__content__body" in html or "mainFIOdropbtn" in html
    except Exception:
        return False


def ensure_login(page, api, profile, unattended=False, wait_seconds=LOGIN_WAIT_SECONDS):
    """Открывает список заявлений; если не авторизованы — ждёт ручного входа."""
    try:
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as exc:
        log("  Не удалось открыть портал: %s" % str(exc).splitlines()[0][:160])
        return False

    if is_authenticated(page):
        return True

    if unattended:
        log("  Профиль '%s': сессия истекла, вход нужен вручную — пропускаем" % profile)
        return False

    log("  Профиль '%s': нужен вход. В открывшемся окне Chrome войдите на портал" % profile)
    log("  (ЭЦП через NCALayer или логин/пароль). Скрипт продолжит сам после входа.")
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(3)
        if is_authenticated(page) or session_alive(api):
            log("  Вход выполнен ✓")
            try:
                page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            return True
    log("  Не дождались входа за %d сек — профиль пропущен" % wait_seconds)
    return False


ROWS_JS = """
() => {
  const rows = [];
  document.querySelectorAll('#table__content__body tr').forEach(tr => {
    const link = tr.querySelector('a[href*="/Requests/Details/"]');
    if (!link) return;
    const m = (link.getAttribute('href') || '').match(/\\/Requests\\/Details\\/(\\d+)/);
    if (!m) return;
    const field = (label) => {
      const div = [...tr.querySelectorAll('.row__content__title')]
        .find(d => (d.textContent || '').trim().startsWith(label));
      if (!div) return '';
      const span = div.querySelector('span');
      return (span ? span.textContent : div.textContent.replace(label, '')).trim();
    };
    const statusCell = tr.querySelector('td:last-child p');
    rows.push({
      id: m[1],
      number: field('Номер заявления'),
      created: field('Дата создания'),
      filled: field('Дата заполнения'),
      sent: field('Дата отправки'),
      activity: field('Вид деятельности'),
      licensiar: field('Лицензиар'),
      type: field('Тип заявления'),
      status: statusCell ? statusCell.innerText.replace(/\\s+/g, ' ').trim() : ''
    });
  });
  return rows;
}
"""

TOTAL_PAGES_JS = """
() => {
  const inp = document.querySelector('.pagination input[type=number][max]');
  if (inp) { const v = parseInt(inp.getAttribute('max'), 10); if (v > 0) return v; }
  let max = 1;
  document.querySelectorAll('.pagination .pages a').forEach(a => {
    const v = parseInt((a.textContent || '').trim(), 10);
    if (!isNaN(v) && v > max) max = v;
  });
  return max;
}
"""


def open_list_page(page, base_url, number):
    url = "%s?page=%d" % (base_url, number)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    return is_authenticated(page)


# --------------------------------------------------------------------------
# Скачивание PDF
# --------------------------------------------------------------------------

def source_urls(request_id, lang):
    """Ссылки-кандидаты на PDF заявления (в порядке приоритета)."""
    return {
        "df": "%s/Handlers/DataFormHandler.ashx?id=%s&lang=%s" % (BASE_URL, request_id, lang),
        "page": "%s/Requests/SaveRequestPageAsPdf?requestId=%s&language=%s" % (BASE_URL, request_id, lang),
    }


def request_file_urls(api, request_id, lang):
    """Файлы заявления из /Requests/GetFileListByRequest (нужен schemeId)."""
    urls = []
    try:
        resp = api.get("%s/Requests/GetFileListByRequest?id=%s" % (BASE_URL, request_id),
                       timeout=60000)
        if not resp.ok:
            return urls
        data = resp.json()
        items = data.get("result") if isinstance(data, dict) else data
        for it in items or []:
            item_lang = (it.get("Language") or it.get("Lang") or "").lower()
            urls.append((0 if item_lang == lang else 1,
                         "%s/Requests/GetFileRequestByLanguage/%s?language=%s&schemeId=%s"
                         % (BASE_URL, request_id, item_lang or lang, it.get("SchemeId", ""))))
        urls.sort()
    except Exception:
        return []
    return [u for _, u in urls]


def fetch(api, url, tries=3):
    """GET с ретраями. Возвращает (body, headers) либо (None, причина)."""
    delay = 2
    last = "нет ответа"
    for attempt in range(1, tries + 1):
        try:
            resp = api.get(url, timeout=120000)
            if resp.ok:
                body = resp.body()
                if body[:4] == b"%PDF":
                    return body, resp.headers
                ctype = (resp.headers.get("content-type") or "").lower()
                if "pdf" in ctype and body:
                    return body, resp.headers
                last = "не PDF (%s, %d байт)" % (ctype.split(";")[0] or "?", len(body))
                return None, last          # ответ есть, но это не файл — не ретраим
            last = "HTTP %d" % resp.status
            if resp.status in (401, 403, 404):
                return None, last          # смысла повторять нет
        except Exception as exc:
            last = str(exc).splitlines()[0][:140]
        if attempt < tries:
            time.sleep(delay)
            delay *= 2
    return None, last


def download_request(api, row, out_dir, sources, lang):
    """Скачивает PDF по одному заявлению. Возвращает (путь|None, сообщение)."""
    request_id = row["id"]
    number = row.get("number") or request_id
    fixed = source_urls(request_id, lang)
    problems = []

    for key in sources:
        candidates = request_file_urls(api, request_id, lang) if key == "req" else [fixed[key]]
        if key == "req" and not candidates:
            problems.append("req: файлов нет")
            continue
        for url in candidates:
            body, info = fetch(api, url)
            if body:
                name = filename_from_cd(info.get("content-disposition"))
                if not name or not name.lower().endswith(".pdf"):
                    name = "Request_%s_%s.pdf" % (number, key)
                path = unique_path(out_dir, sanitize_filename(name))
                path.write_bytes(body)
                return path, key
            problems.append("%s: %s" % (key, info))
    return None, "; ".join(problems) or "источники не дали PDF"


# --------------------------------------------------------------------------
# Основной проход по профилю
# --------------------------------------------------------------------------

def crawl_profile(pw, args, profile, state, out_dir):
    """Обходит списки заявлений профиля и скачивает всё новое."""
    log("=" * 62)
    log("Профиль: %s" % profile)
    seen = profile_state(state, profile)
    stats = {"new": 0, "skip": 0, "fail": 0, "seen": 0}

    ctx = launch_context(pw, args, profile)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        api = ctx.request          # общие с браузером cookie
        if not ensure_login(page, api, profile, args.unattended, args.login_wait):
            return stats

        lists = [("Мои заявления", LIST_URL)]
        if args.include_pending:
            lists.append(("Требуют действий", PENDING_URL))

        for list_name, list_url in lists:
            if not open_list_page(page, list_url, args.first_page):
                log("  Список '%s' недоступен — пропуск" % list_name)
                continue
            try:
                total_pages = page.evaluate(TOTAL_PAGES_JS)
            except Exception:
                total_pages = 1
            last_page = min(args.last_page or total_pages, total_pages)
            log("  %s: страниц %d, обрабатываем %d–%d"
                % (list_name, total_pages, args.first_page, last_page))

            known_streak = 0
            stop = False
            for page_no in range(args.first_page, last_page + 1):
                if page_no != args.first_page:
                    if not open_list_page(page, list_url, page_no):
                        if not ensure_login(page, api, profile, args.unattended, args.login_wait):
                            log("  Сессия потеряна — профиль остановлен")
                            break
                        open_list_page(page, list_url, page_no)
                try:
                    rows = page.evaluate(ROWS_JS)
                except Exception as exc:
                    log("  Стр. %d: не разобрать список (%s)" % (page_no, str(exc)[:100]))
                    continue
                if not rows:
                    log("  Стр. %d: пусто — дальше не идём" % page_no)
                    break

                log("  Стр. %d/%d: заявлений %d" % (page_no, last_page, len(rows)))
                for row in rows:
                    stats["seen"] += 1
                    number = row.get("number") or row["id"]
                    created = parse_date(row.get("created"))

                    if args.since and created and created < args.since:
                        log("    %s: старше %s — стоп по дате"
                            % (number, args.since.strftime("%d.%m.%Y")))
                        stop = True
                        break

                    owner, fname = (None, None) if args.redownload \
                        else existing_copy(state, number, out_dir)
                    if owner:
                        stats["skip"] += 1
                        known_streak += 1
                        if owner != profile:
                            log("    %s: уже скачано под профилем '%s' — пропуск"
                                % (number, owner))
                        if args.stop_after_known and known_streak >= args.stop_after_known:
                            log("    %d подряд уже скачанных — дальше новых нет"
                                % known_streak)
                            stop = True
                            break
                        continue
                    prev = seen.get(number)
                    if prev and prev.get("ok"):
                        log("    %s: файла нет в папке — качаем заново" % number)
                    known_streak = 0

                    path, info = download_request(api, row, out_dir, args.sources, args.lang)
                    stamp = dt.datetime.now().isoformat(timespec="seconds")
                    if path:
                        stats["new"] += 1
                        seen[number] = {"ok": True, "id": row["id"], "file": path.name,
                                        "source": info, "at": stamp}
                        log("    %s → %s" % (number, path.name))
                        append_index([profile, number, row["id"], row.get("created", ""),
                                      row.get("status", ""), row.get("activity", ""),
                                      path.name, stamp])
                    else:
                        stats["fail"] += 1
                        seen[number] = {"ok": False, "id": row["id"],
                                        "error": info, "at": stamp}
                        log("    %s: не скачано (%s)" % (number, info))
                    save_state(state)
                    time.sleep(args.delay)

                    if args.limit and stats["new"] >= args.limit:
                        log("    Достигнут лимит --limit %d" % args.limit)
                        stop = True
                        break
                if stop:
                    break
    finally:
        try:
            ctx.close()
        except Exception:
            pass
        save_state(state)

    log("  Итог по профилю '%s': новых %d, пропущено %d, ошибок %d"
        % (profile, stats["new"], stats["skip"], stats["fail"]))
    return stats


# --------------------------------------------------------------------------
# Команды
# --------------------------------------------------------------------------

def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        print("Не найден Playwright. Установите его:\n"
              "    pip install playwright\n"
              "    playwright install chromium\n", file=sys.stderr)
        raise SystemExit(2)


def cmd_setup(args):
    """Создать профили и войти в портал под каждым (вручную, по очереди)."""
    sync_playwright = require_playwright()
    names = args.names or ["default"]
    with sync_playwright() as pw:
        for name in names:
            log("Открываю Chrome для профиля '%s'" % name)
            try:
                ctx = launch_context(pw, args, name)
            except Exception as exc:
                log("Не удалось запустить браузер: %s" % str(exc).splitlines()[0][:200])
                log("Установите Chrome либо выполните: %s -m playwright install chromium"
                    % Path(sys.executable).name)
                log("Если Chrome стоит нестандартно, укажите путь: --chrome-path \"...\"")
                return
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                ok = ensure_login(page, ctx.request, name, unattended=False,
                                  wait_seconds=args.login_wait)
                if ok:
                    log("Профиль '%s' готов. Окно можно закрыть." % name)
                    if not args.keep_open:
                        input("Нажмите Enter, чтобы перейти к следующему профилю... ")
                else:
                    log("Профиль '%s' не авторизован." % name)
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
    log("Профили: %s" % ", ".join(known_profiles(args.profiles_dir)) or "нет")


def cmd_list(args):
    names = known_profiles(args.profiles_dir)
    state = load_state()
    if not names:
        print("Профилей нет. Создайте: python3 %s setup имя1 имя2"
              % Path(sys.argv[0]).name)
        return
    print("Папка профилей: %s" % (Path(args.profiles_dir).expanduser()
                                  if args.profiles_dir else PROFILES_DIR))
    for n in names:
        done = sum(1 for v in state["profiles"].get(n, {}).values() if v.get("ok"))
        bad = sum(1 for v in state["profiles"].get(n, {}).values() if not v.get("ok"))
        print("  • %-20s скачано: %-6d ошибок: %d" % (n, done, bad))
    print("Файлы: %s" % target_dir(args.out))


def cmd_run(args):
    sync_playwright = require_playwright()
    profiles = args.profiles or known_profiles(args.profiles_dir)
    if args.user_data_dir:
        profiles = profiles or ["chrome"]
    if not profiles:
        print("Нет ни одного профиля. Сначала: python3 %s setup имя1 имя2"
              % Path(sys.argv[0]).name, file=sys.stderr)
        raise SystemExit(1)

    out_dir = target_dir(args.out)
    log("Папка выгрузки: %s" % out_dir)
    log("Профили: %s" % ", ".join(profiles))

    state = load_state()
    iteration = 0
    while True:
        iteration += 1
        totals = {"new": 0, "skip": 0, "fail": 0}
        with sync_playwright() as pw:
            for profile in profiles:
                try:
                    st = crawl_profile(pw, args, profile, state, out_dir)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    log("Профиль '%s': сбой — %s" % (profile, str(exc).splitlines()[0][:200]))
                    continue
                for k in totals:
                    totals[k] += st.get(k, 0)
        save_state(state)
        log("=" * 62)
        log("Проход %d завершён: новых файлов %d, пропущено %d, ошибок %d"
            % (iteration, totals["new"], totals["skip"], totals["fail"]))
        log("Всё сложено в %s" % out_dir)

        if not args.watch:
            break
        # В режиме наблюдения повторные проходы делаем короткими
        if not args.full_scan and not args.stop_after_known:
            args.stop_after_known = DEFAULT_STOP_AFTER_KNOWN
        log("Следующая проверка через %d мин (Ctrl+C — выход)" % args.watch)
        try:
            time.sleep(args.watch * 60)
        except KeyboardInterrupt:
            log("Остановлено пользователем")
            break


# --------------------------------------------------------------------------
# Разбор аргументов
# --------------------------------------------------------------------------

def add_browser_args(p):
    p.add_argument("--profiles-dir", help="папка с профилями (по умолчанию %s)" % PROFILES_DIR)
    p.add_argument("--user-data-dir",
                   help="использовать существующий каталог профилей Chrome "
                        "(Chrome при этом должен быть полностью закрыт)")
    p.add_argument("--profile-directory",
                   help="имя профиля внутри --user-data-dir, например 'Profile 1'")
    p.add_argument("--login-wait", type=int, default=LOGIN_WAIT_SECONDS,
                   help="сколько секунд ждать ручного входа (по умолчанию %d)" % LOGIN_WAIT_SECONDS)
    p.add_argument("--chrome-path", help="путь к исполняемому файлу Chrome/Chromium, "
                                         "если он стоит не в стандартном месте")
    p.add_argument("--no-sandbox", action="store_true",
                   help="запускать браузер с --no-sandbox (нужно в редких случаях)")


def parse_pages_range(value):
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", value or "")
    if not m:
        raise argparse.ArgumentTypeError("формат: 5 или 1-20")
    first = int(m.group(1))
    last = int(m.group(2)) if m.group(2) else None
    if first < 1 or (last and last < first):
        raise argparse.ArgumentTypeError("некорректный диапазон страниц")
    return first, last


def parse_since(value):
    d = parse_date(value)
    if not d:
        raise argparse.ArgumentTypeError("дата в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД")
    return d


def build_parser():
    p = argparse.ArgumentParser(
        description="Выгрузка PDF-заявлений с портала elicense.kz в папку "
                    "'Заявления' на рабочем столе.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Типовые команды:")[1].split("Зависимости:")[0]
        if "Типовые команды:" in __doc__ else None)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="создать профили и войти в портал вручную")
    s.add_argument("names", nargs="*", help="имена профилей, например: ivan petr")
    s.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--keep-open", action="store_true",
                   help="не ждать Enter между профилями")
    add_browser_args(s)
    s.set_defaults(func=cmd_setup)

    l = sub.add_parser("list", help="показать профили и статистику")
    l.add_argument("--out", help="папка выгрузки")
    add_browser_args(l)
    l.set_defaults(func=cmd_list)

    r = sub.add_parser("run", help="скачать заявления по всем профилям")
    r.add_argument("-p", "--profile", dest="profiles", action="append",
                   help="профиль (можно указать несколько раз); "
                        "по умолчанию — все заведённые")
    r.add_argument("--out", help="папка выгрузки (по умолчанию <Рабочий стол>/Заявления)")
    r.add_argument("--pages", type=parse_pages_range, default=(1, None),
                   help="диапазон страниц списка, например 1-20")
    r.add_argument("--since", type=parse_since,
                   help="брать заявления не старше даты (ДД.ММ.ГГГГ)")
    r.add_argument("--limit", type=int, default=0,
                   help="остановиться после N новых файлов на профиль")
    r.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                   help="пауза между скачиваниями, сек (по умолчанию %.1f)" % DEFAULT_DELAY)
    r.add_argument("--lang", choices=("ru", "kz"), default="ru",
                   help="язык документа (по умолчанию ru)")
    r.add_argument("--source", dest="sources", action="append", choices=SOURCE_KEYS,
                   help="источник PDF: df (форма сведений), req (файл заявления), "
                        "page (печать страницы); по умолчанию пробуются все по очереди")
    r.add_argument("--stop-after-known", type=int, default=0,
                   help="остановиться после N подряд уже скачанных заявлений "
                        "(ускоряет регулярные запуски, например 30)")
    r.add_argument("--full-scan", action="store_true",
                   help="всегда проходить все страницы целиком")
    r.add_argument("--redownload", action="store_true",
                   help="скачивать заново даже то, что уже есть")
    r.add_argument("--include-pending", action="store_true",
                   help="дополнительно обойти список 'требующих действий'")
    r.add_argument("--watch", type=int, metavar="МИНУТ",
                   help="повторять проход каждые N минут")
    r.add_argument("--unattended", action="store_true",
                   help="не ждать ручного входа: профиль без сессии пропускается")
    r.add_argument("--headless", action="store_true",
                   help="без окна браузера (только если вход уже выполнен)")
    add_browser_args(r)
    r.set_defaults(func=cmd_run)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "run":
        args.first_page, args.last_page = args.pages
        args.sources = args.sources or list(SOURCE_KEYS)
        if args.full_scan:
            args.stop_after_known = 0
    for name, default in (("unattended", False), ("include_pending", False),
                          ("headless", False), ("out", None)):
        if not hasattr(args, name):
            setattr(args, name, default)
    try:
        args.func(args)
    except KeyboardInterrupt:
        log("Прервано пользователем")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
