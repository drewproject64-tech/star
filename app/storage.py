from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Storage:
    """SQLite persistence for user submissions."""

    def __init__(self, path: str = "data/star.db") -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            connection.commit()

    def add_submission(self, user_id: int, username: str | None, text: str) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO submissions(user_id, username, text, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, text, created_at),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def get_mode(self) -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM bot_settings WHERE key='mode'").fetchone()
            return row["value"] if row else "normal"

    def set_mode(self, mode: str) -> None:
        if mode not in {"normal", "promotion"}:
            raise ValueError("Unsupported bot mode")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO bot_settings(key, value) VALUES('mode', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (mode,),
            )
            connection.commit()
