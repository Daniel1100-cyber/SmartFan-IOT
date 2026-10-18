@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo First run SETUP.bat to install the project dependencies.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" run.py
if errorlevel 1 pause
