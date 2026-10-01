@echo off
rem MX5 Bridge firmware patcher (window). Drag an updater (.exe/.zip) onto this file to preselect it.
rem Console version: python patcher.py [updater]
cd /d "%~dp0"
py patcher_gui.py %*
if errorlevel 9009 python patcher_gui.py %*
if errorlevel 1 pause
