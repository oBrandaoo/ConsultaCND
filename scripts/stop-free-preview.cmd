@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-free-preview.ps1" %*
