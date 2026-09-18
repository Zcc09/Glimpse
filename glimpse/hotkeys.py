"""Global hotkeys: RegisterHotKey on a hidden window + a Qt native event filter."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from .config import parse_hotkey
from .log import log

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

# stable ids so tests (and logs) can post WM_HOTKEY deterministically
FIXED_IDS = {"capture": 1, "translate": 2, "visual": 3, "songid": 4, "record": 5}


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def _event_type_str(event_type) -> str:
    """PySide6 hands us a QByteArray — str() of it is "b'windows_generic_MSG'"."""
    if isinstance(event_type, (bytes, bytearray)):
        return bytes(event_type).decode("utf-8", "replace")
    try:
        return bytes(event_type).decode("utf-8", "replace")
    except Exception:
        s = str(event_type)
        if s.startswith("b'") and s.endswith("'"):
            return s[2:-1]
        if s.startswith('b"') and s.endswith('"'):
            return s[2:-1]
        return s


def _msg_int(message) -> int:
    for attr in ("toint", "to_int"):
        f = getattr(message, attr, None)
        if callable(f):
            try:
                return int(f())
            except Exception:
                pass
    try:
        return int(message)
    except Exception:
        return 0


class HotkeyManager(QObject, QAbstractNativeEventFilter):
    triggered = Signal(str)  # action name

    def __init__(self, hwnd: int, parent=None):
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._hwnd = int(hwnd)
        self._ids: dict[int, str] = {}
        self._last_fire: dict[str, float] = {}
        self._next_id = 1
        self._user32 = ctypes.windll.user32

    # ------------------------------------------------------------ registration
    def _free_id(self) -> int:
        while self._next_id in self._ids or self._next_id in FIXED_IDS.values():
            self._next_id += 1
        hotkey_id = self._next_id
        self._next_id += 1
        return hotkey_id

    def register(self, action: str, spec: str) -> str | None:
        """Register one hotkey. Returns None on success, else an error message."""
        parsed = parse_hotkey(spec)
        if parsed is None:
            return f"'{spec}' is not a valid hotkey"
        mods, vk = parsed
        hotkey_id = FIXED_IDS.get(action)
        if hotkey_id is None or hotkey_id in self._ids:
            hotkey_id = self._free_id()
        ok = self._user32.RegisterHotKey(wintypes.HWND(self._hwnd), hotkey_id, mods | MOD_NOREPEAT, vk)
        if not ok:
            err = ctypes.get_last_error() or "already in use"
            return f"'{spec}' could not be registered ({err})"
        self._ids[hotkey_id] = action
        log.info("hotkey registered: %s → %s (id %s)", spec, action, hotkey_id)
        return None

    def unregister_all(self) -> None:
        for hotkey_id in list(self._ids):
            try:
                self._user32.UnregisterHotKey(wintypes.HWND(self._hwnd), hotkey_id)
            except Exception:
                pass
        self._ids.clear()
        self._next_id = 1

    def set_hotkeys(self, mapping: dict[str, str]) -> dict[str, str]:
        """(Re)register everything. Returns {action: error} for failures."""
        self.unregister_all()
        errors: dict[str, str] = {}
        for action, spec in mapping.items():
            if not spec:
                continue
            err = self.register(action, spec)
            if err:
                errors[action] = err
        return errors

    # ------------------------------------------------------------ Qt filter
    def nativeEventFilter(self, event_type, message):  # noqa: N802
        et = _event_type_str(event_type)
        if et in ("windows_generic_MSG", "windows_dispatcher_MSG"):
            try:
                msg = MSG.from_address(_msg_int(message))
            except Exception:
                return False
            if msg.message == WM_HOTKEY:
                action = self._ids.get(int(msg.wParam))
                if action:
                    now = time.time()
                    # the same message can be delivered twice (dispatcher + window proc)
                    if now - self._last_fire.get(action, 0.0) < 0.4:
                        return True
                    self._last_fire[action] = now
                    log.info("hotkey fired: %s", action)
                    self.triggered.emit(action)
                    return True
        return False
