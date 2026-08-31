#!/usr/bin/env bash
# Установка выгрузки заявлений elicense.kz (macOS / Linux).
# Запуск:  bash install.sh
set -u
cd "$(dirname "$0")" || exit 1

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo
    echo "  Не найден Python 3.8 или новее."
    echo "  macOS:  brew install python3"
    echo "  Ubuntu: sudo apt install python3 python3-pip"
    echo
    exit 1
fi

exec "$PY" install.py
