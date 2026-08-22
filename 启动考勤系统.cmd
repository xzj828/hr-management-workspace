@echo off
cd /d "%~dp0"
powershell -NoLogo -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1"

