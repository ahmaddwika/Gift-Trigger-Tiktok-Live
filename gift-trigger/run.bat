@echo off
setlocal
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  python GiftTrigger.py
) else (
  start "" pythonw GiftTrigger.py
)
