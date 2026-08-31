@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Скачивание заявлений elicense.kz

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (python -c "import sys" >nul 2>&1 && set "PY=python")

if not defined PY (
    echo.
    echo   Python не найден. Сначала запустите "Установка.bat".
    echo.
    pause
    exit /b 1
)

%PY% download_zayavleniya.py run
echo.
pause
