@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-app.ps1"
if errorlevel 1 exit /b 1
call "%~dp0notes.cmd"
