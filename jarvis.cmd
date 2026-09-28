@echo off
rem Jarvis CLI fuer Windows — im Projektordner doppelklicken oder "jarvis" tippen.
rem Sucht einen lauffaehigen Python-Interpreter und startet die CLI damit; die CLI
rem selbst braucht keine Abhaengigkeiten, also funktioniert das auch vor der Installation.
setlocal
cd /d "%~dp0"

set "JARVIS_PY="
call :probe "py -3"
if defined JARVIS_PY goto :run
call :probe "python"
if defined JARVIS_PY goto :run
call :probe "python3"
if defined JARVIS_PY goto :run

rem Klassische per-User-Installation von python.org unter %LOCALAPPDATA%.
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
  if not defined JARVIS_PY call :probe "%%D\python.exe"
)
if defined JARVIS_PY goto :run

echo.
echo   Python 3.10 oder neuer wird benoetigt und wurde nicht gefunden.
echo   Installieren von https://www.python.org/downloads/ , dann hier erneut starten.
echo.
pause
exit /b 1

:probe
%1 --version >nul 2>nul
if %ERRORLEVEL%==0 set "JARVIS_PY=%1"
exit /b 0

:run
%JARVIS_PY% jarvis.py %*
endlocal