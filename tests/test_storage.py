import sqlite3
from pathlib import Path

from app.storage import Storage


def test_sqlite_connections_close_and_data_persists(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    connections = []
    original_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            connections.append(self)
            super().close()

    def tracked_connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=TrackedConnection)

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    source = tmp_path / "recovered.txt"
    source.write_text("8647561557\n123\n123\n", encoding="utf-8")
    path = str(tmp_path / "users.db")
    storage = Storage(path)
    assert storage.import_user_ids(source) == 2
    assert storage.import_user_ids(source) == 0
    assert storage.remember_user(456)
    assert not storage.remember_user(456)
    assert storage.add_submission(456, "user", "Test") == 1
    storage.activate_for_known_users(now=100)
    assert storage.get_mode() == "registration"
    assert not storage.due_sequences(now=105)
    storage.pause_promotions()
    assert not storage.due_sequences(now=1000)
    assert Storage(path).user_stats()["total"] == 3
    for _ in range(100):
        storage.get_mode()
    for connection in connections:
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError("Database connection leaked")


def test_postgres_migration(tmp_path, monkeypatch):
    import os
    import pytest

    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL must point to a disposable database")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = str(tmp_path / "old.db")
    old = Storage(path)
    old.remember_user(8647561557)
    old.add_submission(8647561557, "user", "Original")
    old.activate_for_known_users(now=100)
    monkeypatch.setenv("DATABASE_URL", database_url)
    storage = Storage(path)
    assert 8647561557 in storage.known_users()
    assert storage.get_mode() == "registration"
    assert storage.add_submission(8647561557, "user", "New") == 2
    storage.set_mode("normal")
    assert Storage(path).get_mode() == "normal"
