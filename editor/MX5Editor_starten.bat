@echo off
cd /d "%~dp0"
py mx5editor.py
if errorlevel 1 python mx5editor.py
pause
