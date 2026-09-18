"""Single-instance guard over QLocalSocket (second launch pokes the first).

The server name is derived from the data dir, so separate profiles/portable
copies (and the test suite, which uses its own GLIMPSE_HOME) never collide.
"""
from __future__ import annotations

import hashlib

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .log import log
from .paths import app_dir

BASE_NAME = "Glimpse.SingleInstance.v2"


def instance_name() -> str:
    digest = hashlib.sha1(str(app_dir()).lower().encode("utf-8")).hexdigest()[:12]
    return f"{BASE_NAME}.{digest}"


def notify_primary(message: str = "show", timeout_ms: int = 400) -> bool:
    """Send `message` to a running instance. True when delivered."""
    sock = QLocalSocket()
    sock.connectToServer(instance_name())
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(message.encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class SingleInstance(QObject):
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server: QLocalServer | None = None

    def try_primary(self) -> bool:
        """Become the primary instance. False when another one is running."""
        if notify_primary("ping"):
            return False
        name = instance_name()
        QLocalServer.removeServer(name)  # stale socket from a crash
        self.server = QLocalServer(self)
        if not self.server.listen(name):
            log.warning("could not listen on %s: %s", name, self.server.errorString())
            return True  # carry on; hotkeys still work
        self.server.newConnection.connect(self._on_connection)
        return True

    def _on_connection(self) -> None:
        if not self.server:
            return
        sock = self.server.nextPendingConnection()
        if not sock:
            return
        sock.readyRead.connect(lambda: self._read(sock))
        sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock: QLocalSocket) -> None:
        data = bytes(sock.readAll()).decode("utf-8", "replace").strip()
        if data and data != "ping":
            self.message.emit(data)
