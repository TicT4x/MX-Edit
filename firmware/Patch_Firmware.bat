@echo off
rem MX5 Bridge firmware patcher - builds the updater from the official HeadRush MX5 2.7 updater.
rem Drag the official updater (.zip/.exe) or a NAM mod updater (.exe) onto this file to use it
rem instead of downloading.
cd /d "%~dp0"
py patcher.py %*
if errorlevel 9009 python patcher.py %*
pause
