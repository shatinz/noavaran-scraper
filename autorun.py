r"""
Windows Startup Autorun Manager for Noavaran Panjereh Scraper.
Manages HKCU\Software\Microsoft\Windows\CurrentVersion\Run registry keys
without requiring administrative privileges.
"""

import os
import sys
from typing import Dict, Any, Tuple

REG_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "NoavaranPanjerehScraper"


def _get_executable_command(auto_crawl: bool = True) -> str:
    """
    Get the exact command string to launch on Windows startup.
    Works whether running as compiled .exe or Python script.
    """
    flag = " --autorun" if auto_crawl else ""
    if getattr(sys, "frozen", False):
        exe_path = sys.executable
        return f'"{exe_path}"{flag}'
    else:
        python_exe = sys.executable
        main_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
        return f'"{python_exe}" "{main_py}"{flag}'


def is_autorun_enabled() -> bool:
    """Check if the application is registered to run on Windows startup."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ) as key:
            try:
                val, _ = winreg.QueryValueEx(key, APP_REG_NAME)
                return bool(val)
            except FileNotFoundError:
                return False
    except Exception:
        return False


def set_autorun(enable: bool, auto_crawl: bool = True) -> Tuple[bool, str]:
    """
    Enable or disable daily autorun on Windows startup.
    Returns (success, message).
    """
    if sys.platform != "win32":
        return False, "Autorun is only supported on Windows operating systems."

    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_ALL_ACCESS) as key:
            if enable:
                cmd = _get_executable_command(auto_crawl=auto_crawl)
                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, cmd)
                return True, "اجرای خودکار با موفقیت در ویندوز فعال شد."
            else:
                try:
                    winreg.DeleteValue(key, APP_REG_NAME)
                except FileNotFoundError:
                    pass
                return True, "اجرای خودکار در ویندوز غیرفعال شد."
    except Exception as e:
        return False, f"خطا در تغییر تنظیمات استارت‌آپ ویندوز: {str(e)}"


def get_autorun_info() -> Dict[str, Any]:
    """Get full details on current autorun configuration."""
    if sys.platform != "win32":
        return {"supported": False, "enabled": False, "command": ""}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ) as key:
            try:
                val, _ = winreg.QueryValueEx(key, APP_REG_NAME)
                return {
                    "supported": True,
                    "enabled": True,
                    "command": val,
                    "auto_crawl": "--autorun" in val,
                }
            except FileNotFoundError:
                return {"supported": True, "enabled": False, "command": "", "auto_crawl": False}
    except Exception:
        return {"supported": True, "enabled": False, "command": "", "auto_crawl": False}
