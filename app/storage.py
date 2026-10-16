from __future__ import annotations

import sqlite3
import os
from contextlib import contextmanager
from typing import Iterator
import time
from datetime import datetime, timezone
from pathlib import Path

from app.content import BONUS_DELAY_SECONDS, PROMOTION_INTERVAL_SECONDS, NEW_USER_SEQUENCE_DELAYS, NEW_USER_SEQUENCE, ROTATION_INTERVAL_SECONDS, ROTATION_MESSAGES


class PostgresConnection:
    """Expose the small connection API used by Storage for either database."""
    def __init__(self, connection) -> None:
        self.connection = connection

    def execute(self, query: str, params=()):
        return self.connection.execute(query.replace("?", "%s"), params)

    def executemany(self, query: str, params):
        cursor = self.connection.cursor()
        cursor.executemany(query.replace("?", "%s"), params)
        return cursor

    def commit(self) -> None:
        self.connection.commit()


class Storage:
    """SQLite persistence for submissions, mode and per-user message schedules."""

    def __init__(self, path: str = "data/star.db") -> None:
        self.path = Path(path)
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        self.postgres = bool(self.database_url)
        if self.postgres and not self.database_url.startswith(("postgres://", "postgresql://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection URL")
        if not self.postgres and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if self.postgres:
            self._migrate_sqlite()

    @contextmanager
    def _connect(self) -> Iterator:
        # SQLite's own context manager commits but does not close the connection.
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10) as raw:
                yield PostgresConnection(raw)
        else:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            id_column = "BIGSERIAL PRIMARY KEY" if self.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
            connection.execute(f"""
                CREATE TABLE IF NOT EXISTS submissions (
                    id {id_column},
                    user_id BIGINT NOT NULL,
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
                    chat_id BIGINT PRIMARY KEY,
                    next_promo_at DOUBLE PRECISION,
                    bonus_at DOUBLE PRECISION,
                    withdrawal_step INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    sequence_step INTEGER NOT NULL DEFAULT 0,
                    sequence_next_at DOUBLE PRECISION
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (
                    chat_id BIGINT PRIMARY KEY,
                    source TEXT NOT NULL,
                    first_start_at DOUBLE PRECISION,
                    last_start_at DOUBLE PRECISION
                )
            """)
            connection.execute(
                "INSERT INTO user_activity(chat_id, source) "
                "SELECT chat_id, 'existing' FROM promo_users WHERE chat_id>0 "
                "ON CONFLICT(chat_id) DO NOTHING"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS rotation_jobs (
                    chat_id BIGINT PRIMARY KEY,
                    step INTEGER NOT NULL DEFAULT 0,
                    next_at DOUBLE PRECISION NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    generation INTEGER NOT NULL DEFAULT 1
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS account_deliveries (
                    campaign_id TEXT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    next_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY(campaign_id, chat_id)
                )
            """)
            # Migrate databases created by older versions.
            if self.postgres:
                columns = {row["name"] for row in connection.execute(
                    "SELECT column_name AS name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='promo_users'"
                )}
            else:
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(promo_users)")}
            if "sequence_step" not in columns:
                connection.execute("ALTER TABLE promo_users ADD COLUMN sequence_step INTEGER NOT NULL DEFAULT 0")
            if "sequence_next_at" not in columns:
                connection.execute("ALTER TABLE promo_users ADD COLUMN sequence_next_at DOUBLE PRECISION")
            connection.commit()

    def _migrate_sqlite(self) -> None:
        """Copy surviving local data once; never overwrite newer PostgreSQL rows."""
        if not self.path.is_file():
            return
        with self._connect() as target:
            if target.execute("SELECT value FROM bot_settings WHERE key='sqlite_migration_done'").fetchone():
                return
            source = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
            source.row_factory = sqlite3.Row
            try:
                tables = {row["name"] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ("submissions", "promo_users", "user_activity", "bot_settings", "rotation_jobs", "account_deliveries"):
                    if table not in tables:
                        continue
                    for row in source.execute(f"SELECT * FROM {table}"):
                        columns = list(row.keys())
                        placeholders = ", ".join("?" for _ in columns)
                        target.execute(
                            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                            tuple(row),
                        )
                target.execute(
                    "SELECT setval(pg_get_serial_sequence('submissions', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM submissions), 1), "
                    "EXISTS(SELECT 1 FROM submissions))"
                )
                target.execute(
                    "INSERT INTO user_activity(chat_id, source) "
                    "SELECT chat_id, 'existing' FROM promo_users WHERE chat_id>0 ON CONFLICT DO NOTHING"
                )
                target.execute(
                    "INSERT INTO bot_settings(key, value) VALUES('sqlite_migration_done', '1') "
                    "ON CONFLICT(key) DO NOTHING"
                )
                target.commit()
            finally:
                source.close()

    def queue_account_notice(self, campaign_id: str, now: float | None = None) -> None:
        """Queue once for all current users; restarts never requeue completed deliveries."""
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO account_deliveries(campaign_id, chat_id, next_at) "
                "SELECT ?, chat_id, ? FROM promo_users WHERE chat_id>0 "
                "ON CONFLICT(campaign_id, chat_id) DO NOTHING", (campaign_id, now)
            )

    def due_account_notices(self, campaign_id: str, now: float | None = None) -> list:
        now = time.time() if now is None else now
        with self._connect() as connection:
            return list(connection.execute(
                "SELECT chat_id FROM account_deliveries WHERE campaign_id=? "
                "AND status='pending' AND next_at<=? ORDER BY next_at, chat_id LIMIT 100",
                (campaign_id, now),
            ))

    def finish_account_notice(self, campaign_id: str, chat_id: int, status: str = "sent") -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO account_deliveries(campaign_id, chat_id, status, next_at) VALUES (?, ?, ?, 0) "
                "ON CONFLICT(campaign_id, chat_id) DO UPDATE SET status=excluded.status",
                (campaign_id, chat_id, status),
            )

    def retry_account_notice(self, campaign_id: str, chat_id: int, delay: float) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE account_deliveries SET next_at=? WHERE campaign_id=? AND chat_id=? AND status='pending'",
                (time.time() + max(1, delay), campaign_id, chat_id),
            )

    def add_submission(self, user_id: int, username: str | None, text: str) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO submissions(user_id, username, text, created_at) VALUES (?, ?, ?, ?) RETURNING id",
                (user_id, username, text, created_at),
            )
            submission_id = int(cursor.fetchone()["id"])
            connection.commit()
            return submission_id

    def get_mode(self) -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM bot_settings WHERE key='mode'").fetchone()
            mode = row["value"] if row else "normal"
            return "registration" if mode == "promotion" else mode

    def set_mode(self, mode: str) -> None:
        if mode not in {"normal", "registration", "promotion"}:
            raise ValueError("Unsupported bot mode")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO bot_settings(key, value) VALUES('mode', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("registration" if mode == "promotion" else mode,),
            )
            connection.commit()

    def enable_registration(self) -> None:
        """Enter registration mode; wait for the explicit Send Broadcast action."""
        self.stop_rotation()
        self.set_mode("registration")

    def rotation_running(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM bot_settings WHERE key='rotation_running'").fetchone()
            return bool(row and row["value"] == "1")

    def activate_for_known_users(self, now: float | None = None) -> int:
        """Enable registration mode and restart the image rotation for saved users."""
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO bot_settings(key, value) VALUES('mode', 'registration') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            connection.execute("UPDATE promo_users SET enabled=0")
            connection.execute(
                "INSERT INTO bot_settings(key, value) VALUES('rotation_running', '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            connection.execute(
                """INSERT INTO rotation_jobs(chat_id, step, next_at, enabled, generation)
                   SELECT chat_id, 0, ?, 1, 1 FROM promo_users WHERE chat_id>0
                   ON CONFLICT(chat_id) DO UPDATE SET step=0, next_at=excluded.next_at,
                   enabled=1, generation=rotation_jobs.generation+1""", (now,)
            )
            count = connection.execute("SELECT COUNT(*) AS n FROM promo_users WHERE chat_id>0").fetchone()["n"]
            connection.commit()
            return count

    def queue_rotation_for_user(self, chat_id: int, now: float | None = None) -> None:
        if chat_id <= 0:
            return
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO rotation_jobs(chat_id, step, next_at, enabled)
                   SELECT ?, 0, ?, 1 WHERE EXISTS(
                       SELECT 1 FROM bot_settings WHERE key='rotation_running' AND value='1')
                   ON CONFLICT(chat_id) DO UPDATE SET enabled=1""", (chat_id, now)
            )
            connection.commit()

    def due_rotation(self, now: float | None = None) -> list:
        now = time.time() if now is None else now
        with self._connect() as connection:
            return list(connection.execute(
                "SELECT chat_id, step, generation FROM rotation_jobs "
                "WHERE enabled=1 AND next_at<=? ORDER BY next_at, chat_id LIMIT 100", (now,)
            ))

    def rotation_job_is_current(self, chat_id: int, step: int, generation: int) -> bool:
        with self._connect() as connection:
            return bool(connection.execute(
                "SELECT chat_id FROM rotation_jobs WHERE chat_id=? AND step=? AND generation=? AND enabled=1",
                (chat_id, step, generation),
            ).fetchone())

    def finish_rotation_job(self, chat_id: int, step: int, generation: int,
                            now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                "UPDATE rotation_jobs SET step=?, next_at=? "
                "WHERE chat_id=? AND step=? AND generation=? AND enabled=1",
                ((step + 1) % len(ROTATION_MESSAGES), now + ROTATION_INTERVAL_SECONDS,
                 chat_id, step, generation),
            )
            connection.commit()

    def retry_rotation_job(self, chat_id: int, generation: int, delay: float) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE rotation_jobs SET next_at=? WHERE chat_id=? AND generation=?",
                (time.time() + delay, chat_id, generation),
            )
            connection.commit()

    def disable_rotation_user(self, chat_id: int, generation: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE rotation_jobs SET enabled=0 WHERE chat_id=? AND generation=?",
                (chat_id, generation),
            )
            connection.commit()

    def stop_rotation(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO bot_settings(key, value) VALUES('mode', 'normal') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            connection.execute(
                "INSERT INTO bot_settings(key, value) VALUES('rotation_running', '0') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            connection.execute("UPDATE rotation_jobs SET enabled=0, generation=generation+1")
            connection.execute("UPDATE promo_users SET enabled=0")
            connection.commit()

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
            cursor = connection.executemany(
                "INSERT INTO promo_users(chat_id, enabled) VALUES (?, 0) "
                "ON CONFLICT(chat_id) DO NOTHING",
                [(chat_id,) for chat_id in sorted(chat_ids)],
            )
            added = cursor.rowcount
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
            total = connection.execute("SELECT COUNT(*) AS n FROM promo_users WHERE chat_id>0").fetchone()["n"]
            sources = {r["source"]: r["n"] for r in connection.execute(
                "SELECT source, COUNT(*) AS n FROM user_activity GROUP BY source"
            )}
            new_24h = connection.execute(
                "SELECT COUNT(*) AS n FROM user_activity WHERE source='new' AND first_start_at>=?",
                (now - 86400,),
            ).fetchone()["n"]
            new_7d = connection.execute(
                "SELECT COUNT(*) AS n FROM user_activity WHERE source='new' AND first_start_at>=?",
                (now - 7 * 86400,),
            ).fetchone()["n"]
            active_24h = connection.execute(
                "SELECT COUNT(*) AS n FROM user_activity WHERE last_start_at>=?", (now - 86400,)
            ).fetchone()["n"]
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
