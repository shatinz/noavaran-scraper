@echo off
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
