"""Autostart via HKCU Run key (packaged builds only)."""
from __future__ import annotations

import sys

from . import __app_name__
from .log import log
from .paths import is_frozen

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE = __app_name__


def supported() -> bool:
    return is_frozen()


def _command() -> str:
    return f'"{sys.executable}" --tray'


def is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, _VALUE)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as e:  # noqa: BLE001
        log.debug("autostart read failed: %s", e)
        return False


def set_enabled(enabled: bool) -> bool:
    if not supported():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, _VALUE, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(k, _VALUE)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("autostart write failed: %s", e)
        return False
