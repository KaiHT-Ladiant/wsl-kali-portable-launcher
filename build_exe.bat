@echo off
chcp 65001 >nul
title Kali Launcher - PyInstaller Build

cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo 오류: python을 찾을 수 없습니다.
    pause
    exit /b 1
)

python -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller 설치 중...
    python -m pip install pyinstaller
)

if not exist "kali_icon.ico" (
    echo 오류: kali_icon.ico 가 없습니다.
    pause
    exit /b 1
)

echo exe 빌드 중...
python -m PyInstaller --onefile --windowed --name KaliLauncher ^
  --icon=kali_icon.ico ^
  --add-data "kali_icon.ico;." ^
  --add-data "kali_icon.png;." ^
  --version-file=version_info.txt ^
  --clean kali_launcher.py

if %errorlevel% equ 0 (
    copy /Y "kali_icon.ico" "dist\kali_icon.ico" >nul 2>&1
    copy /Y "kali_icon.png" "dist\kali_icon.png" >nul 2>&1
    echo.
    echo 완료: %~dp0dist\KaliLauncher.exe
) else (
    echo 빌드 실패
)

pause
