@echo off
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
