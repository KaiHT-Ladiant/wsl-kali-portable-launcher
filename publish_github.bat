@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Ensure core Windows tools are visible
if defined SystemRoot set "PATH=%SystemRoot%\System32;%SystemRoot%;%PATH%"

rem Refresh PATH so newly installed tools (gh, git) are visible
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "MachinePath=%%B"
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "UserPath=%%B"
if defined MachinePath set "PATH=%MachinePath%;%PATH%"
if defined UserPath set "PATH=%PATH%;%UserPath%"

set "PS_EXE="
if exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" (
    set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
) else if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" (
    set "PS_EXE=%ProgramFiles%\PowerShell\7\pwsh.exe"
)

if not defined PS_EXE (
    echo PowerShell not found.
    echo Install PowerShell or run: .\publish_github.ps1
    pause
    exit /b 1
)

"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_github.ps1"
set "exitcode=%ERRORLEVEL%"

if not "%exitcode%"=="0" (
    echo.
    echo Publish failed with exit code %exitcode%.
    pause
    exit /b %exitcode%
)

pause
