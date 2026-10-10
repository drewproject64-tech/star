from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from app.content import BONUS_DELAY_SECONDS, PROMOTION_INTERVAL_SECONDS


class Storage:
    """SQLite persistence for submissions, mode and per-user promotion schedule."""

    def __init__(self, path: str = "data/star.db") -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
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
            connection.execute("""
                CREATE TABLE IF NOT EXISTS promo_users (
                    chat_id INTEGER PRIMARY KEY,
                    next_promo_at REAL,
                    bonus_at REAL,
                    withdrawal_step INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 0
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

    def remember_user(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO promo_users(chat_id, enabled) VALUES (?, 0) "
                "ON CONFLICT(chat_id) DO NOTHING", (chat_id,)
            )
            connection.commit()

    def known_users(self) -> list[int]:
        with self._connect() as connection:
            return [int(row["chat_id"]) for row in connection.execute("SELECT chat_id FROM promo_users")]

    def has_promotion_schedule(self, chat_id: int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT next_promo_at FROM promo_users WHERE chat_id=?", (chat_id,)
            ).fetchone()
            return bool(row and row["next_promo_at"] is not None)

    def enable_promotion_for_user(self, chat_id: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO promo_users(chat_id, next_promo_at, bonus_at, withdrawal_step, enabled)
                   VALUES (?, ?, ?, 0, 1)
                   ON CONFLICT(chat_id) DO UPDATE SET next_promo_at=excluded.next_promo_at,
                   bonus_at=excluded.bonus_at, withdrawal_step=0, enabled=1""",
                (chat_id, now + PROMOTION_INTERVAL_SECONDS, now + BONUS_DELAY_SECONDS),
            )
            connection.commit()

    def resume_promotions(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE promo_users SET enabled=1 WHERE next_promo_at IS NOT NULL"
            )
            connection.commit()

    def due_bonuses(self, now: float | None = None) -> list[int]:
        now = time.time() if now is None else now
        with self._connect() as connection:
            return [int(r["chat_id"]) for r in connection.execute(
                "SELECT chat_id FROM promo_users WHERE enabled=1 AND bonus_at IS NOT NULL AND bonus_at<=?", (now,)
            )]

    def mark_bonus_sent(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE promo_users SET bonus_at=NULL WHERE chat_id=?", (chat_id,))
            connection.commit()

    def due_promotions(self, now: float | None = None) -> list[sqlite3.Row]:
        now = time.time() if now is None else now
        with self._connect() as connection:
            return list(connection.execute(
                "SELECT chat_id, withdrawal_step FROM promo_users "
                "WHERE enabled=1 AND next_promo_at IS NOT NULL AND next_promo_at<=?", (now,)
            ))

    def mark_promotion_sent(self, chat_id: int, next_step: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                "UPDATE promo_users SET withdrawal_step=?, next_promo_at=? WHERE chat_id=?",
                (next_step, now + 2 * 60 * 60, chat_id),
            )
            connection.commit()

    def pause_promotions(self) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE promo_users SET enabled=0")
            connection.commit()
