#!/usr/bin/env python3
"""Скачивание заявлений через профили самого Chrome — с выбором из списка.

Показывает профили, которые вы завели в Chrome ("Добавить профиль"),
даёт выбрать нужные номерами и запускает выгрузку под каждым по очереди.

Запуск:  python3 chrome_run.py
На Windows — двойной клик по "Скачать через профили Chrome.bat".
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN = HERE / "download_zayavleniya.py"

sys.path.insert(0, str(HERE))
from download_zayavleniya import chrome_profiles, chrome_user_data_dir  # noqa: E402


def choose(found):
    """Разбор ответа пользователя: номера, имена или пусто = все."""
    print()
    print("  Введите номера нужных профилей через запятую (например: 1,3)")
    print("  или просто Enter — взять все.")
    try:
        answer = input("  Ваш выбор: ").strip()
    except EOFError:
        answer = ""

    if not answer:
        return [name for _, name in found]

    picked = []
    for part in answer.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit() and 1 <= int(part) <= len(found):
            picked.append(found[int(part) - 1][1])
            continue
        match = [name for folder, name in found
                 if part.lower() in (folder.lower(), name.lower())]
        if match:
            picked.append(match[0])
        else:
            print("  ! Профиль '%s' не найден — пропускаю" % part)
    return picked


def main():
    print("=" * 62)
    print("  Выгрузка заявлений через профили Chrome")
    print("=" * 62)
    print()
    print("  ВАЖНО: Chrome должен быть полностью закрыт (все окна),")
    print("  иначе Windows не даст открыть его профиль.")
    print()

    found = chrome_profiles()
    if not found:
        print("  Профили Chrome не найдены.")
        print("  Каталог Chrome: %s" % (chrome_user_data_dir() or "не найден"))
        print()
        print("  Если Chrome установлен, но профилей нет — запустите его хотя бы раз.")
        print("  Либо заведите отдельные профили скрипта:")
        print("      %s download_zayavleniya.py setup имя1 имя2"
              % Path(sys.executable).name)
        return 1

    print("  Профили Chrome:")
    for i, (folder, name) in enumerate(found, 1):
        print("   %2d. %-24s (папка %s)" % (i, name, folder))

    picked = choose(found)
    if not picked:
        print("  Ничего не выбрано.")
        return 1

    cmd = [sys.executable, str(MAIN), "run"]
    for name in picked:
        cmd += ["--chrome-profile", name]
    cmd += sys.argv[1:]          # можно дописать свои ключи, например --since

    print()
    print("  Запускаю: %s" % " ".join(cmd[1:]))
    print()
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nПрервано.")
        sys.exit(130)
