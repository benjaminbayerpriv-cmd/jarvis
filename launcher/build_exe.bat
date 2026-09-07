@echo off
rem Builds launcher\dist\Jarvis.exe — a double-click app whose own window
rem *is* the web interface (via pywebview/WebView2, not a browser tab). It
rem starts the existing .venv-based server in the background and shuts it
rem down when the window closes. Run this once, on Windows, after
rem SETUP.md's install steps.
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Bitte zuerst die Installation aus SETUP.md ausfuehren.
  pause
  exit /b 1
)

.venv\Scripts\python.exe -m pip install --quiet pyinstaller pywebview
.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name Jarvis ^
  --distpath launcher\dist --workpath launcher\build --specpath launcher ^
  launcher\jarvis_launcher.py

echo.
echo Fertig: launcher\dist\Jarvis.exe
pause
