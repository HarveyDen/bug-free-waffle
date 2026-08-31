@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Диагностика выгрузки заявлений

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (python -c "import sys" >nul 2>&1 && set "PY=python")

if not defined PY (
    echo.
    echo   Python не найден — значит, установка не проходила.
    echo   Запустите "Установка.bat".
    echo.
    pause
    exit /b 1
)

%PY% download_zayavleniya.py doctor
echo.
echo ============================================================
echo   Профили самого Chrome:
echo ============================================================
%PY% download_zayavleniya.py chrome-profiles
echo.
echo   Скопируйте весь текст выше и пришлите его.
echo.
pause
