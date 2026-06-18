@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Refresh PATH so newly installed tools (gh, git) are visible
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "MachinePath=%%B"
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "UserPath=%%B"
if defined MachinePath set "PATH=%MachinePath%"
if defined UserPath set "PATH=%PATH%;%UserPath%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_github.ps1"
set "exitcode=%ERRORLEVEL%"

if not "%exitcode%"=="0" (
    echo.
    echo Publish failed with exit code %exitcode%.
    pause
    exit /b %exitcode%
)

pause
