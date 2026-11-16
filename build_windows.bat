@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .buildvenv
call .buildvenv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
call .buildvenv\Scripts\pyinstaller.exe --noconfirm --clean --onedir --windowed --name Prescriber_Intelligence --paths app --collect-all duckdb app\main.py
if errorlevel 1 exit /b 1
echo Portable application built in dist\Prescriber_Intelligence\
pause
