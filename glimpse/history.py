"""History store: SQLite + PNG files under the app data dir."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QImage

from .log import log
from .paths import app_dir, captures_dir, history_path
from .util import png_bytes, qimage_from_bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    title TEXT DEFAULT '',
    text TEXT DEFAULT '',
    extra TEXT DEFAULT '{}',
    image_path TEXT DEFAULT '',
    thumb_path TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts DESC);
"""


class History:
    def __init__(self, path: Path | str | None = None, limit: int = 500):
        self.path = str(path or history_path())
        self.limit = int(limit or 500)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------ writes
    def add(
        self,
        kind: str,
        title: str = "",
        text: str = "",
        extra: Optional[dict] = None,
        image: Optional[QImage] = None,
        image_bytes: Optional[bytes] = None,
    ) -> int:
        image_path = ""
        thumb_path = ""
        if image is not None or image_bytes:
            data = image_bytes if image_bytes is not None else png_bytes(image)
            month = time.strftime("%Y-%m")
            folder = captures_dir() / month
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
            full = folder / f"{name}.png"
            full.write_bytes(data)
            image_path = str(full)
            if image is not None:
                try:
                    from PySide6.QtCore import Qt

                    thumb = image.scaledToWidth(420, Qt.TransformationMode.SmoothTransformation)
                    (folder / f"{name}_thumb.png").write_bytes(png_bytes(thumb))
                    thumb_path = str(folder / f"{name}_thumb.png")
                except Exception:
                    thumb_path = image_path
            else:
                thumb_path = image_path
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO entries (ts, kind, title, text, extra, image_path, thumb_path) "
                "VALUES (?,?,?,?,?,?,?)",
                (time.time(), kind, title or "", text or "", json.dumps(extra or {}, ensure_ascii=False), image_path, thumb_path),
            )
            self.conn.commit()
            row_id = int(cur.lastrowid)
            self.prune()
        return row_id

    def set_extra(self, entry_id: int, extra: dict) -> None:
        with self._lock:
            self.conn.execute("UPDATE entries SET extra=? WHERE id=?", (json.dumps(extra, ensure_ascii=False), entry_id))
            self.conn.commit()

    def delete(self, entry_id: int) -> None:
        with self._lock:
            row = self.conn.execute("SELECT image_path, thumb_path FROM entries WHERE id=?", (entry_id,)).fetchone()
            self.conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))
            self.conn.commit()
        for p in row or []:
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass

    def clear(self) -> None:
        with self._lock:
            rows = self.conn.execute("SELECT image_path, thumb_path FROM entries").fetchall()
            self.conn.execute("DELETE FROM entries")
            self.conn.commit()
        for r in rows:
            for p in r:
                if p:
                    try:
                        Path(p).unlink(missing_ok=True)
                    except OSError:
                        pass

    def prune(self) -> None:
        try:
            with self._lock:
                if self.limit <= 0:
                    return
                old = self.conn.execute(
                    "SELECT id, image_path, thumb_path FROM entries ORDER BY ts DESC LIMIT -1 OFFSET ?",
                    (self.limit,),
                ).fetchall()
                for row in old:
                    self.conn.execute("DELETE FROM entries WHERE id=?", (row[0],))
                    for p in row[1:]:
                        if p:
                            try:
                                Path(p).unlink(missing_ok=True)
                            except OSError:
                                pass
                if old:
                    self.conn.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("prune failed: %s", e)

    # ------------------------------------------------------------ reads
    def _row(self, r) -> dict:
        return {
            "id": r[0],
            "ts": r[1],
            "kind": r[2],
            "title": r[3],
            "text": r[4],
            "extra": json.loads(r[5] or "{}"),
            "image_path": r[6],
            "thumb_path": r[7],
        }

    def get(self, entry_id: int) -> Optional[dict]:
        with self._lock:
            r = self.conn.execute(
                "SELECT id, ts, kind, title, text, extra, image_path, thumb_path FROM entries WHERE id=?",
                (entry_id,),
            ).fetchone()
        return self._row(r) if r else None

    def list_entries(self, limit: int = 300, kind: str | None = None, query: str = "") -> list[dict]:
        sql = "SELECT id, ts, kind, title, text, extra, image_path, thumb_path FROM entries"
        args: list = []
        where = []
        if kind:
            where.append("kind=?")
            args.append(kind)
        if query:
            where.append("(title LIKE ? OR text LIKE ?)")
            args += [f"%{query}%", f"%{query}%"]
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [self._row(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0])

    def load_image(self, entry: dict) -> Optional[QImage]:
        p = entry.get("image_path") or entry.get("thumb_path")
        if not p:
            return None
        try:
            return qimage_from_bytes(Path(p).read_bytes())
        except Exception:
            return None

    def load_thumb(self, entry: dict) -> Optional[QImage]:
        p = entry.get("thumb_path") or entry.get("image_path")
        if not p:
            return None
        try:
            return qimage_from_bytes(Path(p).read_bytes())
        except Exception:
            return None
