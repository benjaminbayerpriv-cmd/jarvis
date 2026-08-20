@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Bitte zuerst die Installation aus SETUP.md ausfuehren.
  pause
  exit /b 1
)

start "Jarvis Hotkey" /min ".venv\Scripts\python.exe" "launcher\hotkey_listener.py"
".venv\Scripts\python.exe" -m backend.main
