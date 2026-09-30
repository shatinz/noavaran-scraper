"""
Build and packaging script for Noavaran Panjereh Lead Discovery Scraper.
Produces:
1. Self-contained NoavaranScraper.exe (via PyInstaller)
2. 1-click Windows Installer (install.bat)
3. 1-click Uninstaller (uninstall.bat)
4. Inno Setup configuration (installer.iss)
5. Complete distribution ZIP: dist/NoavaranScraper-Windows-x64.zip
"""

import os
import sys
import shutil
import zipfile
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
PACKAGE_DIR = os.path.join(DIST_DIR, "NoavaranScraper-Package")

INSTALL_BAT_CONTENT = r"""@echo off
chcp 65001 >nul
title Noavaran Panjereh Scraper - Quick Installer
color 0b

echo ================================================================
echo    Noavaran Panjereh Lead & Project Discovery Scraper
echo    نرم‌افزار استخراج سرنخ و پروژه‌های ساختمانی نوآوران پنجره
echo ================================================================
echo.
echo Installing to: %LOCALAPPDATA%\Programs\NoavaranScraper
echo [1/3] Copying application files...

set "TARGET_DIR=%LOCALAPPDATA%\Programs\NoavaranScraper"
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

if exist "%~dp0NoavaranScraper.exe" (
    set "SOURCE_EXE=%~dp0NoavaranScraper.exe"
) else if exist "%~dp0dist\NoavaranScraper.exe" (
    set "SOURCE_EXE=%~dp0dist\NoavaranScraper.exe"
) else (
    echo [ERROR] NoavaranScraper.exe was not found!
    pause
    exit /b 1
)
copy /y "%SOURCE_EXE%" "%TARGET_DIR%\NoavaranScraper.exe" >nul
if exist "%~dp0icon.ico" copy /y "%~dp0icon.ico" "%TARGET_DIR%\icon.ico" >nul

echo [2/3] Creating Desktop and Start Menu shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$WshShell = New-Object -ComObject WScript.Shell; " ^
  "$DeskPath = [Environment]::GetFolderPath('Desktop'); " ^
  "$StartPath = [Environment]::GetFolderPath('Programs'); " ^
  "$AppPath = '%TARGET_DIR%\NoavaranScraper.exe'; " ^
  "$IconPath = '%TARGET_DIR%\icon.ico'; " ^
  "$DeskShortcut = $WshShell.CreateShortcut(\"$DeskPath\Noavaran Panjereh Scraper.lnk\"); " ^
  "$DeskShortcut.TargetPath = $AppPath; " ^
  "$DeskShortcut.WorkingDirectory = '%TARGET_DIR%'; " ^
  "if (Test-Path $IconPath) { $DeskShortcut.IconLocation = $IconPath }; " ^
  "$DeskShortcut.Description = 'Noavaran Panjereh Scraper'; " ^
  "$DeskShortcut.Save(); " ^
  "$StartShortcut = $WshShell.CreateShortcut(\"$StartPath\Noavaran Panjereh Scraper.lnk\"); " ^
  "$StartShortcut.TargetPath = $AppPath; " ^
  "$StartShortcut.WorkingDirectory = '%TARGET_DIR%'; " ^
  "if (Test-Path $IconPath) { $StartShortcut.IconLocation = $IconPath }; " ^
  "$StartShortcut.Description = 'Noavaran Panjereh Scraper'; " ^
  "$StartShortcut.Save();"

echo [3/3] Setting up Uninstaller...
(
echo @echo off
echo title Uninstall Noavaran Panjereh Scraper
echo echo Removing shortcuts...
echo del "%USERPROFILE%\Desktop\Noavaran Panjereh Scraper.lnk" 2^>nul
echo del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Noavaran Panjereh Scraper.lnk" 2^>nul
echo echo Removing program files...
echo rmdir /s /q "%TARGET_DIR%" 2^>nul
echo echo Noavaran Panjereh Scraper was uninstalled successfully.
echo pause
) > "%TARGET_DIR%\uninstall.bat"

copy /y "%TARGET_DIR%\uninstall.bat" "%~dp0uninstall.bat" >nul

echo.
echo ================================================================
echo    [SUCCESS] Installation complete! نصب با موفقیت انجام شد
echo.
echo    * Shortcut added to Desktop (میانبر در دسکتاپ ایجاد شد)
echo    * Added to Windows Start Menu (به منوی استارت اضافه شد)
echo    * Runs on any 64-bit Windows without installing Python
echo ================================================================
echo.
set /p LAUNCH="Launch Noavaran Scraper now? (Y/N) [Y]: "
if /i "%LAUNCH%"=="" set LAUNCH=Y
if /i "%LAUNCH%"=="Y" (
    start "" "%TARGET_DIR%\NoavaranScraper.exe"
)
"""

UNINSTALL_BAT_CONTENT = r"""@echo off
title Uninstall Noavaran Panjereh Scraper
set "TARGET_DIR=%LOCALAPPDATA%\Programs\NoavaranScraper"
echo ================================================================
echo Uninstalling Noavaran Panjereh Scraper...
echo ================================================================
echo Removing shortcuts...
del "%USERPROFILE%\Desktop\Noavaran Panjereh Scraper.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Noavaran Panjereh Scraper.lnk" 2>nul
echo Removing program files...
rmdir /s /q "%TARGET_DIR%" 2>nul
echo.
echo Done! The software has been removed from your system.
pause
"""

README_INSTALL_CONTENT = """================================================================
Noavaran Panjereh Lead & Project Discovery Scraper
راهنمای نصب و اجرای نرم‌افزار نوآوران پنجره روی ویندوز
================================================================

این نرم‌افزار کاملاً پرتابل و مستقل است و بدون نیاز به نصب پایتون (Python)
یا هرگونه پیش‌نیاز دیگر روی تمام سیستم‌های ویندوز ۱۰ و ۱۱ (۶۴ بیتی) اجرا می‌شود.

روش اول: نصب خودکار با ۱ کلیک (پیشنهادی)
----------------------------------------
1. فایل زیپ را Extract (از حالت فشرده خارج) کنید.
2. روی فایل "install.bat" دابل کلیک کنید.
3. میانبر برنامه با آیکون اختصاصی روی دسکتاپ و در منوی استارت ویندوز قرار می‌گیرد.

روش دوم: اجرای مستقیم و پرتابل (بدون نیاز به نصب)
----------------------------------------------
- بدون نیاز به نصب، مستقیماً روی "NoavaranScraper.exe" دابل کلیک کنید.
- برنامه باز شده و دیتابیس و فایل‌های خروجی CSV را در کنار خود یا در پوشه برنامه ذخیره می‌کند.

نکته مهم امنیتی ویندوز (Windows SmartScreen):
--------------------------------------------
در صورت مشاهده پیام "Windows protected your PC" هنگام اولین اجرا:
1. روی گزینه "More info" کلیک کنید.
2. سپس دکمه "Run anyway" را بزنید.
(این پیام به دلیل جدید بودن فایل اجرایی و عدم ثبت لایسنس تجاری مایکروسافت در سیستم مقصد است و کاملاً طبیعی است.)

حذف برنامه (Uninstall):
-----------------------
- برای حذف، کافی است روی فایل "uninstall.bat" دابل کلیک کنید.

================================================================
"""

INNO_SETUP_CONTENT = r"""; Inno Setup Script for Noavaran Panjereh Scraper
; Compile using Inno Setup Compiler (iscc.exe installer.iss)

[Setup]
AppName=Noavaran Panjereh Scraper
AppVersion=1.0.0
AppPublisher=Noavaran Panjereh
DefaultDirName={userappdata}\Programs\NoavaranScraper
DefaultGroupName=Noavaran Panjereh
OutputDir=dist
OutputBaseFilename=NoavaranScraper-Setup
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\NoavaranScraper.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Noavaran Panjereh Scraper"; Filename: "{app}\NoavaranScraper.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{group}\Uninstall Noavaran Panjereh Scraper"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Noavaran Panjereh Scraper"; Filename: "{app}\NoavaranScraper.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\NoavaranScraper.exe"; Description: "{cm:LaunchProgram,Noavaran Panjereh Scraper}"; Flags: nowait postinstall skipifsilent
"""


def main():
    print("=== Building Installation Package for Another Machine ===")
    exe_path = os.path.join(DIST_DIR, "NoavaranScraper.exe")
    if not os.path.exists(exe_path):
        print("Building NoavaranScraper.exe via PyInstaller...")
        subprocess.check_call(["pyinstaller", "NoavaranScraper.spec", "--noconfirm"])
    
    # Prepare package folder
    if os.path.exists(PACKAGE_DIR):
        shutil.rmtree(PACKAGE_DIR)
    os.makedirs(PACKAGE_DIR, exist_ok=True)

    # Copy files into package
    shutil.copy2(exe_path, os.path.join(PACKAGE_DIR, "NoavaranScraper.exe"))
    shutil.copy2(os.path.join(BASE_DIR, "icon.ico"), os.path.join(PACKAGE_DIR, "icon.ico"))

    assets_src = os.path.join(BASE_DIR, "assets")
    if os.path.exists(assets_src):
        shutil.copytree(assets_src, os.path.join(PACKAGE_DIR, "assets"), dirs_exist_ok=True)

    with open(os.path.join(PACKAGE_DIR, "install.bat"), "w", encoding="utf-8") as f:
        f.write(INSTALL_BAT_CONTENT)

    with open(os.path.join(PACKAGE_DIR, "uninstall.bat"), "w", encoding="utf-8") as f:
        f.write(UNINSTALL_BAT_CONTENT)

    with open(os.path.join(PACKAGE_DIR, "README_INSTALL.txt"), "w", encoding="utf-8") as f:
        f.write(README_INSTALL_CONTENT)

    # Also write installer.iss to project root
    with open(os.path.join(BASE_DIR, "installer.iss"), "w", encoding="utf-8") as f:
        f.write(INNO_SETUP_CONTENT)

    # Create ZIP archive
    zip_path = os.path.join(DIST_DIR, "NoavaranScraper-Windows-x64.zip")
    print(f"Creating portable distribution ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(PACKAGE_DIR):
            for file in files:
                file_full = os.path.join(root, file)
                rel_path = os.path.relpath(file_full, PACKAGE_DIR)
                zipf.write(file_full, arcname=rel_path)

    print(f"Successfully generated package at {PACKAGE_DIR}")
    print(f"Successfully generated release ZIP at {zip_path} ({os.path.getsize(zip_path) // (1024*1024)} MB)")


if __name__ == "__main__":
    main()
