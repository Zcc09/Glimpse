"""Logging setup — file log always, console only when one exists."""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from .paths import log_path

log = logging.getLogger("glimpse")


def setup_logging(level: int = logging.INFO) -> None:
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        fh = RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        pass

    stream = getattr(sys, "stderr", None)
    try:
        if stream is not None and stream.fileno() is not None:
            sh = logging.StreamHandler(stream)
            sh.setLevel(level)
            sh.setFormatter(fmt)
            log.addHandler(sh)
    except Exception:
        pass

    def _hook(exc_type, exc, tb):
        log.error("unhandled exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _hook
    threading.excepthook = lambda args: log.error(
        "unhandled thread exception in %s", getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
