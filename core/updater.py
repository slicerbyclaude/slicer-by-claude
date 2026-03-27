"""
Auto-updater for "Slicer by Claude" on Windows.

Mechanism:
- Query GitHub Releases API for `releases/latest`
- Compare latest tag vs current `APP_VERSION`
- Download the release zip asset (or fallback to the first .zip link found in body)
- Extract and find the updated .exe inside the zip
- Replace the running exe via a small cmd "updater" that runs after this process exits
"""

from __future__ import annotations

import os
import re
import sys
import time
import json
import shutil
import zipfile
import tempfile
import urllib.request
import subprocess
from pathlib import Path
from typing import Optional, Tuple


REPO_SLUG = "slicerbyclaude/slicer-by-claude"
GITHUB_API_LATEST = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"


def _is_frozen_exe() -> bool:
    # PyInstaller sets sys.frozen when running a bundled executable.
    return bool(getattr(sys, "frozen", False))


def _current_exe_path() -> Optional[Path]:
    if not _is_frozen_exe():
        return None
    try:
        return Path(sys.executable).resolve()
    except Exception:
        return None


def _parse_version(v: str) -> Tuple[int, int, int]:
    # Accept formats like "v2.0.0" or "2.0.0"
    v = (v or "").strip()
    if v.startswith(("v", "V")):
        v = v[1:]
    parts = v.split(".")
    ints = []
    for p in parts[:3]:
        try:
            ints.append(int(re.sub(r"[^0-9].*$", "", p) or "0"))
        except Exception:
            ints.append(0)
    while len(ints) < 3:
        ints.append(0)
    return ints[0], ints[1], ints[2]


def _fetch_latest_release_json(timeout_s: int = 10) -> dict:
    req = urllib.request.Request(
        GITHUB_API_LATEST,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "slicer-by-claude-updater",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    return json.loads(data)


def _extract_zip_download_url(release_json: dict) -> Optional[str]:
    # Preferred: GitHub API assets[].browser_download_url
    assets = release_json.get("assets") or []
    for a in assets:
        name = (a.get("name") or "").lower()
        url = a.get("browser_download_url") or ""
        if url and name.endswith(".zip"):
            return url

    # Fallback: try to find a ".zip" link in release body markdown.
    body = release_json.get("body") or ""
    m = re.search(r"\((https?://[^)\s]+\.zip)", body, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m2 = re.search(r"(https?://[^)\s]+\.zip)", body, flags=re.IGNORECASE)
    if m2:
        return m2.group(1)

    return None


def _download_file(url: str, dest_path: Path, timeout_s: int = 30) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "slicer-by-claude-updater"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(resp, f)


def _extract_zip(zip_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_dir)


def _find_exe_in_tree(root_dir: Path, preferred_name: Optional[str]) -> Optional[Path]:
    try:
        exes = list(root_dir.rglob("*.exe"))
    except Exception:
        exes = []

    if not exes:
        return None

    if preferred_name:
        for e in exes:
            try:
                if e.name.lower() == preferred_name.lower():
                    return e
            except Exception:
                pass

    # Fallback: choose largest exe (often the main one)
    exes.sort(key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
    return exes[0]


def _write_updater_cmd(old_exe: Path, new_exe: Path, script_path: Path) -> None:
    # Powershell is used for robust file copy and locking checks.
    old_s = str(old_exe)
    new_s = str(new_exe)
    script_text = f"""@echo off
setlocal
set "OLD_EXE={old_s}"
set "NEW_EXE={new_s}"

:: Wait until OLD_EXE is not locked by the running process
:wait_lock
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"try {{ $s=[IO.File]::OpenRead($env:OLD_EXE); $s.Close(); exit 0 }} catch {{ exit 1 }}"
if %errorlevel% neq 0 (
  timeout /t 1 /nobreak >nul
  goto wait_lock
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"Copy-Item -Force -ErrorAction Stop $env:NEW_EXE $env:OLD_EXE"

start "" $env:OLD_EXE
exit /b 0
"""
    script_path.write_text(script_text, encoding="utf-8", newline="\r\n")


def maybe_update_self(
    current_version: str,
    settings: Optional[dict] = None,
    min_interval_hours: int = 12,
) -> bool:
    """
    Returns True if an update was scheduled (process should exit).
    Returns False otherwise.
    """
    if not _is_frozen_exe():
        return False

    settings = settings or {}
    last_ts = settings.get("last_update_check_ts")
    now = int(time.time())
    if isinstance(last_ts, int) and min_interval_hours > 0:
        if now - last_ts < (min_interval_hours * 3600):
            return False

    current = _parse_version(current_version)

    try:
        release = _fetch_latest_release_json(timeout_s=10)
        tag = str(release.get("tag_name") or release.get("name") or "")
        latest = _parse_version(tag)
        if latest <= current:
            return False

        zip_url = _extract_zip_download_url(release)
        if not zip_url:
            return False

        # UI-friendly message (best-effort)
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo(
                "Actualización disponible",
                f"Hay una nueva versión ({tag}).\nSe va a actualizar automáticamente.",
            )
            root.destroy()
        except Exception:
            pass

        exe_path = _current_exe_path()
        if not exe_path:
            return False

        preferred_name = exe_path.name
        td_path = Path(tempfile.mkdtemp(prefix="slicer_update_"))
        scheduled = False
        try:
            zip_path = td_path / "update.zip"
            _download_file(zip_url, zip_path)

            extract_dir = td_path / "extracted"
            _extract_zip(zip_path, extract_dir)

            new_exe_path = _find_exe_in_tree(extract_dir, preferred_name=preferred_name)
            if not new_exe_path:
                return False

            # Write updater script next to temp dir (cmd needs the extracted exe paths)
            updater_dir = td_path / "updater"
            updater_dir.mkdir(parents=True, exist_ok=True)
            cmd_path = updater_dir / "run_update.cmd"
            _write_updater_cmd(exe_path, new_exe_path, cmd_path)

            # Start updater and exit immediately.
            subprocess.Popen(["cmd", "/c", str(cmd_path)], close_fds=True)
            scheduled = True
            return True
        finally:
            # If we didn't schedule the updater, clean up.
            if not scheduled:
                try:
                    shutil.rmtree(td_path, ignore_errors=True)
                except Exception:
                    pass
    except Exception:
        # Never crash the app because update failed.
        return False

