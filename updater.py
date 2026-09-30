"""
Auto-Update Engine for Noavaran Scraper
Connects to GitHub Releases API (shatinz/noavaran-scraper), checks for new releases,
downloads updated binaries, and safely swaps executables on Windows using a detached runner.
"""

import os
import sys
import re
import time
import json
import logging
import subprocess
import tempfile
from typing import Optional, Dict, Any, Tuple, Callable
import requests

from database import get_base_dir

logger = logging.getLogger(__name__)

CURRENT_VERSION = "2.1.0"
GITHUB_REPO = "shatinz/noavaran-scraper"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_version(version_str: str) -> Tuple[int, ...]:
    """
    Parses semantic version strings like 'v2.1.0', '2.1.0', or '2.1' into a comparable tuple of integers.
    """
    cleaned = re.sub(r"^[^\d]*", "", version_str.strip())
    # Extract only the numeric components before any pre-release dash
    main_part = cleaned.split("-")[0]
    tokens = [int(p) for p in re.findall(r"\d+", main_part)]
    while len(tokens) < 3:
        tokens.append(0)
    return tuple(tokens[:4])


def check_for_updates(
    current_version: str = CURRENT_VERSION,
    repo_url: str = GITHUB_RELEASES_API,
    timeout: Tuple[float, float] = (5.0, 10.0)
) -> Optional[Dict[str, Any]]:
    """
    Queries GitHub API to determine if a newer release is available.
    Returns release information dictionary if an update is available, or None.
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": f"NoavaranScraper-Updater/{current_version}"
    }

    try:
        response = requests.get(repo_url, headers=headers, timeout=timeout)
        if response.status_code == 404:
            logger.info("No releases found on GitHub repository yet.")
            return None
        if response.status_code != 200:
            logger.warning(f"GitHub Releases API returned status code {response.status_code}")
            return None

        release_data = response.json()
        latest_tag = release_data.get("tag_name", "")
        if not latest_tag:
            return None

        current_v = parse_version(current_version)
        latest_v = parse_version(latest_tag)

        if latest_v <= current_v:
            logger.info(f"Current version {current_version} is up to date (Latest: {latest_tag}).")
            return None

        # Look for executable or distribution archive in release assets
        assets = release_data.get("assets", [])
        download_url = None
        asset_name = None
        asset_size = 0

        # Preference order: .exe first, then .zip
        for asset in assets:
            name = asset.get("name", "")
            if name.lower().endswith(".exe"):
                download_url = asset.get("browser_download_url")
                asset_name = name
                asset_size = asset.get("size", 0)
                break

        if not download_url:
            for asset in assets:
                name = asset.get("name", "")
                if name.lower().endswith(".zip"):
                    download_url = asset.get("browser_download_url")
                    asset_name = name
                    asset_size = asset.get("size", 0)
                    break

        # Fallback to source zipball if no prebuilt asset attached
        if not download_url:
            download_url = release_data.get("zipball_url")
            asset_name = f"NoavaranScraper-{latest_tag}.zip"

        return {
            "has_update": True,
            "current_version": current_version,
            "latest_version": latest_tag,
            "title": release_data.get("name") or latest_tag,
            "release_notes": release_data.get("body", "تغییرات و بهبودهای جدید نسخه منتشر شده است."),
            "download_url": download_url,
            "asset_name": asset_name,
            "asset_size": asset_size,
            "published_at": release_data.get("published_at", "")
        }

    except requests.exceptions.RequestException as e:
        logger.warning(f"Network error checking for updates: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error checking for updates: {e}")
        return None


def download_update(
    download_url: str,
    target_path: Optional[str] = None,
    progress_callback: Optional[Callable[[float, int, int], None]] = None,
    timeout: Tuple[float, float] = (10.0, 60.0)
) -> str:
    """
    Downloads the update package with streaming progress reporting.
    Returns the absolute path to the downloaded file.
    """
    updates_dir = os.path.join(get_base_dir(), "updates")
    os.makedirs(updates_dir, exist_ok=True)

    if not target_path:
        filename = download_url.split("/")[-1].split("?")[0] or "NoavaranScraper_update.exe"
        target_path = os.path.join(updates_dir, filename)

    part_path = target_path + ".part"

    headers = {
        "User-Agent": f"NoavaranScraper-Updater/{CURRENT_VERSION}"
    }

    response = requests.get(download_url, headers=headers, stream=True, timeout=timeout)
    response.raise_for_status()

    total_length = int(response.headers.get("content-length", 0))
    downloaded = 0

    with open(part_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_length > 0:
                    percent = (downloaded / total_length) * 100.0
                    progress_callback(percent, downloaded, total_length)

    if os.path.exists(target_path):
        try:
            os.remove(target_path)
        except OSError:
            pass

    os.replace(part_path, target_path)
    logger.info(f"Update successfully downloaded to: {target_path}")
    return target_path


def apply_update_and_restart(new_binary_path: str, target_exe_path: Optional[str] = None) -> bool:
    """
    Safely applies the update by executing a detached batch script on Windows that:
    1. Waits for the current process (PID) to exit.
    2. Overwrites the target executable with the newly downloaded binary.
    3. Launches the newly updated executable.
    4. Cleans up the temporary update file and batch script.
    """
    if not os.path.exists(new_binary_path):
        raise FileNotFoundError(f"Downloaded binary not found at: {new_binary_path}")

    current_pid = os.getpid()

    if getattr(sys, "frozen", False):
        target_exe = target_exe_path or sys.executable
    else:
        # Development mode fallback
        logger.info("Running in Python development environment. Cannot swap running Python interpreter.")
        return False

    updates_dir = os.path.dirname(os.path.abspath(new_binary_path))
    bat_path = os.path.join(updates_dir, "update_runner.bat")

    # Construct atomic batch update runner
    bat_content = f"""@echo off
chcp 65001 >nul
title Noavaran Scraper Auto-Updater
echo ======================================================
echo    Noavaran Panjereh - Updating Application...
echo ======================================================
echo Waiting for existing process (PID {current_pid}) to terminate...
timeout /t 2 /nobreak >nul

:WAIT_PID
tasklist /fi "PID eq {current_pid}" | find "{current_pid}" >nul
if %errorlevel% equ 0 (
    timeout /t 1 /nobreak >nul
    goto WAIT_PID
)

echo Swapping executable to new version...
copy /y "{new_binary_path}" "{target_exe}" >nul
if %errorlevel% neq 0 (
    echo Retrying file copy in 2 seconds...
    timeout /t 2 /nobreak >nul
    copy /y "{new_binary_path}" "{target_exe}" >nul
)

echo Starting updated application...
start "" "{target_exe}"

echo Cleaning up temporary update files...
del "{new_binary_path}" >nul 2>&1
(goto) 2>nul & del "%~f0"
"""

    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    # Launch batch runner detached from current process tree
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=creation_flags,
        close_fds=True,
        shell=False
    )

    logger.info("Update runner spawned. Exiting current process for swap.")
    sys.exit(0)
