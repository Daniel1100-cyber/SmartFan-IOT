@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Run START.bat.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.12 with the Python launcher and try again.
pause
exit /b 1
