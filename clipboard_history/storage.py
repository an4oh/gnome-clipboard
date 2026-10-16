"""SQLite persistence for the clipboard history.

Ordering rule used everywhere: pinned items first, then most recently used.
Only unpinned items count toward the history limit.
"""
import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LIMIT = 25

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('text', 'image')),
    text TEXT,
    image_path TEXT,
    hash TEXT NOT NULL UNIQUE,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_used_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

ORDER = "ORDER BY pinned DESC, last_used_at DESC, id DESC"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def default_data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "clipboard-history"


@dataclass
class Item:
    id: int
    kind: str
    text: str | None
    image_path: str | None
    hash: str
    pinned: bool
    created_at: float
    last_used_at: float


class Storage:
    def __init__(self, db_path, images_dir, limit=DEFAULT_LIMIT, clock=time.time):
        self.images_dir = Path(images_dir)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.limit = limit
        self.clock = clock
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # --- reads -------------------------------------------------------------

    @staticmethod
    def _item(row):
        if row is None:
            return None
        d = dict(row)
        d["pinned"] = bool(d["pinned"])
        return Item(**d)

    def get(self, item_id):
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._item(row)

    def find_by_hash(self, h):
        row = self.conn.execute("SELECT * FROM items WHERE hash = ?", (h,)).fetchone()
        return self._item(row)

    def list(self, filter_text=None):
        """All items, or only text items containing filter_text (case-insensitive)."""
        if filter_text:
            escaped = filter_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = self.conn.execute(
                f"SELECT * FROM items WHERE kind = 'text' AND text LIKE ? ESCAPE '\\' {ORDER}",
                (f"%{escaped}%",),
            ).fetchall()
        else:
            rows = self.conn.execute(f"SELECT * FROM items {ORDER}").fetchall()
        return [self._item(r) for r in rows]

    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else row["value"]

    # --- writes ------------------------------------------------------------

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, None if value is None else str(value)),
        )
        self.conn.commit()

    def add(self, kind, h, text=None, image_path=None):
        """Insert an item, or move an existing one with the same hash to the top.

        The pin state of an existing item is preserved. Returns the item id.
        """
        now = self.clock()
        existing = self.find_by_hash(h)
        if existing:
            self.conn.execute("UPDATE items SET last_used_at = ? WHERE id = ?", (now, existing.id))
            self.conn.commit()
            return existing.id
        cur = self.conn.execute(
            "INSERT INTO items (kind, text, image_path, hash, pinned, created_at, last_used_at)"
            " VALUES (?, ?, ?, ?, 0, ?, ?)",
            (kind, text, image_path, h, now, now),
        )
        self.conn.commit()
        self.prune()
        return cur.lastrowid

    def add_text(self, text):
        if not text:
            return None
        return self.add("text", content_hash(text.encode("utf-8")), text=text)

    def add_image(self, png_bytes):
        if not png_bytes:
            return None
        h = content_hash(png_bytes)
        path = self.images_dir / f"{h}.png"
        if not path.exists():
            tmp = path.with_suffix(".png.tmp")
            tmp.write_bytes(png_bytes)
            os.replace(tmp, path)
        return self.add("image", h, image_path=str(path))

    def touch(self, item_id):
        self.conn.execute("UPDATE items SET last_used_at = ? WHERE id = ?", (self.clock(), item_id))
        self.conn.commit()

    def pin(self, item_id, pinned=True):
        self.conn.execute("UPDATE items SET pinned = ? WHERE id = ?", (int(bool(pinned)), item_id))
        # No prune on unpin: an item just unpinned should not vanish under the
        # user's cursor; the next add() will enforce the limit.
        self.conn.commit()

    def _delete_rows(self, rows):
        for row in rows:
            self.conn.execute("DELETE FROM items WHERE id = ?", (row["id"],))
        self.conn.commit()
        for row in rows:
            if row["image_path"]:
                try:
                    os.unlink(row["image_path"])
                except FileNotFoundError:
                    pass
        return len(rows)

    def delete(self, item_id):
        rows = self.conn.execute("SELECT id, image_path FROM items WHERE id = ?", (item_id,)).fetchall()
        return self._delete_rows(rows)

    def clear_unpinned(self):
        rows = self.conn.execute("SELECT id, image_path FROM items WHERE pinned = 0").fetchall()
        return self._delete_rows(rows)

    def prune(self, limit=None):
        """Drop the oldest unpinned items beyond the limit."""
        limit = self.limit if limit is None else limit
        rows = self.conn.execute(
            "SELECT id, image_path FROM items WHERE pinned = 0"
            " ORDER BY last_used_at DESC, id DESC LIMIT -1 OFFSET ?",
            (limit,),
        ).fetchall()
        return self._delete_rows(rows)
