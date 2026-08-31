#!/usr/bin/env python3
"""Установщик выгрузки заявлений с elicense.kz.

Делает всё, что нужно перед первым запуском:
  1. проверяет версию Python;
  2. ставит библиотеку playwright;
  3. при необходимости докачивает браузер (если системного Chrome нет);
  4. создаёт папку "Заявления" на рабочем столе;
  5. спрашивает имена профилей и открывает Chrome для входа в каждый.

Запускать из этой же папки:  python3 install.py
На Windows проще двойным кликом по "Установка.bat".
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN = HERE / "download_zayavleniya.py"

# Куда обычно ставится Chrome
CHROME_PATHS = {
    "Windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ],
    "Linux": [
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/opt/google/chrome/chrome",
    ],
}


def say(msg=""):
    print(msg, flush=True)


def step(n, total, title):
    say()
    say("[%d/%d] %s" % (n, total, title))
    say("-" * 60)


def run(cmd, check=True):
    """Запуск команды с показом вывода. Возвращает код возврата."""
    say("  $ " + " ".join(str(c) for c in cmd))
    try:
        proc = subprocess.run(cmd)
    except OSError as exc:
        say("  ! не удалось запустить: %s" % exc)
        return 1
    if check and proc.returncode != 0:
        say("  ! команда завершилась с кодом %d" % proc.returncode)
    return proc.returncode


def find_chrome():
    for path in CHROME_PATHS.get(platform.system(), []):
        if path and Path(path).exists():
            return path
    return None


def desktop_dir():
    """Берём ту же логику, что и в основном скрипте."""
    sys.path.insert(0, str(HERE))
    try:
        from download_zayavleniya import desktop_dir as dd
        return dd()
    except Exception:
        return Path.home() / "Desktop"


def ask(prompt, default=""):
    try:
        answer = input(prompt).strip()
    except EOFError:
        answer = ""
    return answer or default


def main():
    total = 5
    say("=" * 60)
    say("  Установка выгрузки заявлений с elicense.kz")
    say("=" * 60)

    if not MAIN.exists():
        say("Рядом нет файла download_zayavleniya.py — положите install.py")
        say("в ту же папку, что и основной скрипт.")
        return 1

    # 1. Python
    step(1, total, "Проверка Python")
    say("  версия: %s" % sys.version.split()[0])
    say("  система: %s" % platform.platform())
    if sys.version_info < (3, 8):
        say("  ! Нужен Python 3.8 или новее. Обновите Python и запустите снова.")
        return 1
    say("  ок")

    # 2. playwright
    step(2, total, "Установка библиотеки playwright")
    try:
        import playwright  # noqa: F401
        say("  уже установлена")
    except ImportError:
        code = run([sys.executable, "-m", "pip", "install", "playwright"], check=False)
        if code != 0:
            say("  пробуем поставить только для текущего пользователя...")
            code = run([sys.executable, "-m", "pip", "install", "--user", "playwright"],
                       check=False)
        if code != 0:
            say("  ! Не удалось установить playwright.")
            say("    Выполните вручную:  %s -m pip install playwright" % sys.executable)
            return 1
        say("  готово")

    # 3. браузер
    step(3, total, "Браузер")
    chrome = find_chrome()
    if chrome:
        say("  найден Chrome: %s" % chrome)
        say("  скачивать отдельный браузер не нужно")
    else:
        say("  системный Chrome не найден — качаем встроенный Chromium")
        say("  (около 150 МБ, один раз)")
        if run([sys.executable, "-m", "playwright", "install", "chromium"], check=False) != 0:
            say("  ! Браузер скачать не удалось. Установите Chrome — скрипт возьмёт его,")
            say("    либо повторите:  %s -m playwright install chromium" % sys.executable)

    # 4. папка
    step(4, total, "Папка для файлов")
    out = desktop_dir() / "Заявления"
    try:
        out.mkdir(parents=True, exist_ok=True)
        say("  %s" % out)
    except OSError as exc:
        say("  ! не удалось создать папку: %s" % exc)
        say("    ничего страшного — скрипт создаст её при первом запуске")

    # 5. профили
    step(5, total, "Профили (логины портала)")
    existing = []
    try:
        from download_zayavleniya import chrome_profiles
        existing = chrome_profiles()
    except Exception:
        pass
    if existing:
        say("  У вас уже есть профили в самом Chrome:")
        for folder, name in existing:
            say("    • %s  (папка %s)" % (name, folder))
        say()
        say("  Если вы уже входили в портал под ними, отдельные профили не нужны —")
        if platform.system() == "Windows":
            say('  просто закройте Chrome и запустите "Скачать через профили Chrome.bat".')
        else:
            say("  просто закройте Chrome и запустите:  python3 chrome_run.py")
        say()
    say("  Либо заведём отдельные профили скрипта — они не трогают ваш Chrome")
    say("  и работают, даже когда он открыт. Имена латиницей, через пробел.")
    say("  Например:  ivanov petrov ktransgroup")
    say()
    names = ask("  Имена профилей (Enter — пропустить): ").split()

    if not names:
        say()
        say("  Пропущено. Когда будете готовы, выполните:")
        say("      %s download_zayavleniya.py setup имя1 имя2" % Path(sys.executable).name)
        say()
        finish(out)
        return 0

    say()
    say("  Сейчас по очереди откроются окна Chrome — по одному на профиль.")
    say("  В каждом войдите на портал как обычно (ЭЦП через NCALayer либо")
    say("  логин/пароль). Скрипт заметит вход сам.")
    say()
    say("  ВАЖНО: для входа по ЭЦП должен быть запущен NCALayer.")
    ask("  Нажмите Enter, когда будете готовы... ")

    code = run([sys.executable, str(MAIN), "setup"] + names, check=False)
    if code != 0:
        say()
        say("  ! Вход завершился с ошибкой. Можно повторить командой:")
        say("      %s download_zayavleniya.py setup %s"
            % (Path(sys.executable).name, " ".join(names)))

    finish(out)
    return 0


def finish(out):
    say()
    say("=" * 60)
    say("  Готово. Дальше:")
    say("=" * 60)
    if platform.system() == "Windows":
        say('  Скачать заявления        — "Скачать заявления.bat"')
        say('  Через профили Chrome     — "Скачать через профили Chrome.bat"')
        say('  Следить постоянно        — "Следить за новыми.bat"')
        say('  Если что-то не так       — "Диагностика.bat"')
    else:
        say("  Скачать заявления        —  python3 download_zayavleniya.py run")
        say("  Через профили Chrome     —  python3 chrome_run.py")
        say("  Следить постоянно        —  python3 download_zayavleniya.py run --watch 30")
        say("  Если что-то не так       —  python3 download_zayavleniya.py doctor")
    say()
    say("  Файлы будут складываться в:")
    say("      %s" % out)
    say()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say()
        say("Прервано.")
        sys.exit(130)
