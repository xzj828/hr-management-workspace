@echo off
cd /d "%~dp0"
powershell -NoLogo -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\change-password.ps1"
