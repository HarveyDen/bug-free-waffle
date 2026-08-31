@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Установка выгрузки заявлений elicense.kz

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (python -c "import sys" >nul 2>&1 && set "PY=python")

if not defined PY (
    echo.
    echo   Python не найден.
    echo.
    echo   Скачайте Python 3 с сайта python.org, при установке обязательно
    echo   отметьте галочку "Add Python to PATH", затем запустите этот файл снова.
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

%PY% install.py
echo.
pause
