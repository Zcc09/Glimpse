"""Windows uninstall for Glimpse (`Glimpse.exe --uninstall [--silent]`).

Removes shortcuts, the Add/Remove Programs entry and the program files. Your
data (%APPDATA%\\Glimpse: settings, history, recordings) is deliberately kept.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from . import __app_name__
from .log import log

CRLF = "\r\n"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)


def exe_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def install_json() -> dict:
    try:
        with open(os.path.join(exe_dir(), "install.json"), encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def uninstall_targets() -> tuple[str, list[str], str]:
    """(exe_dir, shortcut paths to remove, start menu folder path)."""
    d = exe_dir()
    folder = install_json().get("startmenu_folder") or __app_name__
    desktop = os.path.join(os.path.expanduser("~"), "Desktop", f"{__app_name__}.lnk")
    sm = os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"),
        "Microsoft", "Windows", "Start Menu", "Programs", folder,
    )
    links = [desktop]
    try:
        links += [os.path.join(sm, n) for n in os.listdir(sm)]
    except Exception:
        pass
    return d, links, sm


def is_managed_install(folder: str) -> bool:
    """True only for a folder our Setup created (it must contain install.json)."""
    if not os.path.isfile(os.path.join(folder, "install.json")):
        return False
    home = os.path.expanduser("~")
    banned = set()
    for p in (
        home, os.path.join(home, "Desktop"), os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"), os.path.join(home, "Pictures"),
        os.environ.get("TEMP") or "", os.environ.get("TMP") or "",
        os.environ.get("LOCALAPPDATA") or "", os.environ.get("APPDATA") or "",
        os.environ.get("USERPROFILE") or "",
        "c:\\", "c:\\program files", "c:\\program files (x86)",
        os.environ.get("SystemRoot") or "c:\\windows",
    ):
        if p:
            banned.add(os.path.abspath(p).lower().rstrip("\\"))
    d = os.path.abspath(folder).lower().rstrip("\\")
    return bool(d) and d not in banned and d.count("\\") >= 2 and len(d) > 12


def close_other_instances() -> bool:
    """Close other running Glimpse processes (never ourselves)."""
    cmd = ["taskkill", "/F", "/IM", f"{__app_name__}.exe"]
    for pid in {os.getpid(), os.getppid()}:
        cmd += ["/FI", f"PID ne {pid}"]
    try:
        r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def spawn_folder_delete(folder: str) -> bool:
    """Delete the folder after this process exits (an exe cannot delete itself)."""
    try:
        bat = os.path.join(tempfile.gettempdir(), "glimpse_uninstall.cmd")
        with open(bat, "w", encoding="utf-8", newline="") as f:
            f.write("@echo off" + CRLF)
            f.write("for /L %%i in (1,1,40) do (" + CRLF)
            f.write(f'  rmdir /s /q "{folder}" 2>nul' + CRLF)
            f.write(f'  if not exist "{folder}" goto done' + CRLF)
            f.write("  ping -n 2 127.0.0.1 >nul" + CRLF)
            f.write(")" + CRLF)
            f.write(":done" + CRLF)
            f.write('del /f /q "%~f0"' + CRLF)
        subprocess.Popen(["cmd", "/c", bat], creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("could not schedule folder delete: %s", e)
        return False


def _remove_registry() -> None:
    try:
        import winreg

        winreg.DeleteKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{__app_name__}",
        )
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("registry cleanup failed: %s", e)


def run_uninstall(silent: bool = False) -> int:
    if os.name != "nt":
        print("The uninstaller is Windows-only.")
        return 1
    folder, links, sm = uninstall_targets()
    if not is_managed_install(folder):
        msg = (
            f"This copy was not installed by Setup (no install.json in {folder}), so nothing "
            "was removed: no shortcuts and no Add/Remove entry were touched."
        )
        print(msg)
        return 1

    close_other_instances()
    if not silent:
        answer = input(f"Remove {__app_name__} from {folder}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 1

    removed = 0
    for lnk in links:
        try:
            if os.path.isfile(lnk):
                os.remove(lnk)
                removed += 1
        except OSError:
            pass
    try:
        os.rmdir(sm)  # succeeds only when empty
    except OSError:
        pass
    _remove_registry()

    ok = spawn_folder_delete(folder)
    print(f"{__app_name__} has been uninstalled from {folder} ({removed} shortcut(s) removed).")
    print("Your settings, history and recordings were kept in %APPDATA%\\Glimpse.")
    return 0 if ok else 1
