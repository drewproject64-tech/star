from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from app.content import BONUS_DELAY_SECONDS, PROMOTION_INTERVAL_SECONDS, NEW_USER_SEQUENCE_DELAYS, NEW_USER_SEQUENCE


class Storage:
    """SQLite persistence for submissions, mode and per-user message schedules."""

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
                    enabled INTEGER NOT NULL DEFAULT 0,
                    sequence_step INTEGER NOT NULL DEFAULT 0,
                    sequence_next_at REAL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (
                    chat_id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    first_start_at REAL,
                    last_start_at REAL
                )
            """)
            connection.execute(
                "INSERT OR IGNORE INTO user_activity(chat_id, source) "
                "SELECT chat_id, 'existing' FROM promo_users WHERE chat_id>0"
            )
            # Migrate databases created by older versions.
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(promo_users)")}
            if "sequence_step" not in columns:
                connection.execute("ALTER TABLE promo_users ADD COLUMN sequence_step INTEGER NOT NULL DEFAULT 0")
            if "sequence_next_at" not in columns:
                connection.execute("ALTER TABLE promo_users ADD COLUMN sequence_next_at REAL")
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

    def activate_for_known_users(self, now: float | None = None) -> int:
        """Enable promotion mode and queue the current sequence for saved private chats."""
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO bot_settings(key, value) VALUES('mode', 'promotion') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            connection.execute("UPDATE promo_users SET enabled=0")
            cursor = connection.execute(
                """UPDATE promo_users SET enabled=1, sequence_step=0,
                   sequence_next_at=?, bonus_at=NULL, next_promo_at=NULL
                   WHERE chat_id>0""", (now + 5,)
            )
            connection.commit()
            return cursor.rowcount

    def disable_user_schedule(self, chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE promo_users SET enabled=0 WHERE chat_id=?", (chat_id,))
            connection.commit()

    def remember_user(self, chat_id: int) -> bool:
        """Remember a user and return True only when this is their first recorded start."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO promo_users(chat_id, enabled) VALUES (?, 0) "
                "ON CONFLICT(chat_id) DO NOTHING", (chat_id,)
            )
            connection.commit()
            is_new = cursor.rowcount == 1
            if chat_id > 0:
                now = time.time()
                connection.execute(
                    """INSERT INTO user_activity(chat_id, source, first_start_at, last_start_at)
                       VALUES (?, 'new', ?, ?)
                       ON CONFLICT(chat_id) DO UPDATE SET last_start_at=excluded.last_start_at""",
                    (chat_id, now, now),
                )
                connection.commit()
            return is_new

    def import_user_ids(self, source: Path) -> int:
        """Import recovered private-chat IDs without altering existing schedules."""
        if not source.is_file():
            return 0
        chat_ids = {
            int(line.strip()) for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        if any(chat_id <= 0 for chat_id in chat_ids):
            raise ValueError("Recovered user IDs must be positive private-chat IDs")
        with self._connect() as connection:
            before = connection.total_changes
            connection.executemany(
                "INSERT INTO promo_users(chat_id, enabled) VALUES (?, 0) "
                "ON CONFLICT(chat_id) DO NOTHING",
                [(chat_id,) for chat_id in sorted(chat_ids)],
            )
            added = connection.total_changes - before
            connection.executemany(
                """INSERT INTO user_activity(chat_id, source) VALUES (?, 'recovered')
                   ON CONFLICT(chat_id) DO UPDATE SET source='recovered'
                   WHERE user_activity.source='existing'""",
                [(chat_id,) for chat_id in sorted(chat_ids)],
            )
            connection.commit()
            return added

    def user_stats(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM promo_users WHERE chat_id>0").fetchone()[0]
            sources = {r["source"]: r["n"] for r in connection.execute(
                "SELECT source, COUNT(*) AS n FROM user_activity GROUP BY source"
            )}
            new_24h = connection.execute(
                "SELECT COUNT(*) FROM user_activity WHERE source='new' AND first_start_at>=?",
                (now - 86400,),
            ).fetchone()[0]
            new_7d = connection.execute(
                "SELECT COUNT(*) FROM user_activity WHERE source='new' AND first_start_at>=?",
                (now - 7 * 86400,),
            ).fetchone()[0]
            active_24h = connection.execute(
                "SELECT COUNT(*) FROM user_activity WHERE last_start_at>=?", (now - 86400,)
            ).fetchone()[0]
            recent = [dict(r) for r in connection.execute(
                "SELECT chat_id, source, last_start_at FROM user_activity "
                "WHERE last_start_at IS NOT NULL ORDER BY last_start_at DESC LIMIT 10"
            )]
        return dict(total=total, recovered=sources.get("recovered", 0),
                    existing=sources.get("existing", 0), new=sources.get("new", 0),
                    new_24h=new_24h, new_7d=new_7d, active_24h=active_24h, recent=recent)

    def known_users(self) -> list[int]:
        with self._connect() as connection:
            return [int(row["chat_id"]) for row in connection.execute("SELECT chat_id FROM promo_users")]

    def has_promotion_schedule(self, chat_id: int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT next_promo_at FROM promo_users WHERE chat_id=?", (chat_id,)
            ).fetchone()
            return bool(row and row["next_promo_at"] is not None)

    def start_message_sequence(self, chat_id: int, now: float | None = None) -> None:
        """Schedule sequence message 2 onward, persisting the next due time."""
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO promo_users(
                       chat_id, next_promo_at, bonus_at, withdrawal_step, enabled,
                       sequence_step, sequence_next_at
                   ) VALUES (?, NULL, NULL, 0, 1, 1, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       enabled=1, sequence_step=1, sequence_next_at=excluded.sequence_next_at,
                       bonus_at=NULL""",
                (chat_id, now + NEW_USER_SEQUENCE_DELAYS[0]),
            )
            connection.commit()

    def due_sequences(self, now: float | None = None) -> list[sqlite3.Row]:
        now = time.time() if now is None else now
        with self._connect() as connection:
            return list(connection.execute(
                """SELECT chat_id, sequence_step FROM promo_users
                   WHERE enabled=1 AND sequence_next_at IS NOT NULL AND sequence_next_at<=?""",
                (now,),
            ))

    def mark_sequence_sent(self, chat_id: int, sent_step: int, now: float | None = None) -> None:
        """Advance sequence after a successful send; sent_step is the index just delivered."""
        now = time.time() if now is None else now
        next_step = sent_step + 1
        if next_step >= len(NEW_USER_SEQUENCE):
            next_at = None
            stored_step = 0
        else:
            next_at = now + NEW_USER_SEQUENCE_DELAYS[sent_step]
            stored_step = next_step
        with self._connect() as connection:
            connection.execute(
                "UPDATE promo_users SET sequence_step=?, sequence_next_at=? WHERE chat_id=?",
                (stored_step, next_at, chat_id),
            )
            connection.commit()

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
                "UPDATE promo_users SET enabled=1 WHERE next_promo_at IS NOT NULL OR sequence_next_at IS NOT NULL"
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
                (next_step, now + PROMOTION_INTERVAL_SECONDS, chat_id),
            )
            connection.commit()

    def pause_promotions(self) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE promo_users SET enabled=0")
            connection.commit()
