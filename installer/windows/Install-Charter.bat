@echo off
title Charter - AI Governance Layer - Installer
echo.
echo  ============================================
echo    Charter - AI Governance Layer
echo    Installer for Windows
echo  ============================================
echo.

:: Run the PowerShell installer
powershell -ExecutionPolicy Bypass -File "%~dp0Install-Charter.ps1"

echo.
pause
