@echo off
rem Builds launcher\dist\Jarvis.exe — a thin double-click launcher that
rem starts the existing .venv-based server and opens the browser once it's
rem up. Run this once, on Windows, after SETUP.md's install steps.
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Bitte zuerst die Installation aus SETUP.md ausfuehren.
  pause
  exit /b 1
)

.venv\Scripts\python.exe -m pip install --quiet pyinstaller
.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name Jarvis ^
  --distpath launcher\dist --workpath launcher\build --specpath launcher ^
  launcher\jarvis_launcher.py

echo.
echo Fertig: launcher\dist\Jarvis.exe
pause
