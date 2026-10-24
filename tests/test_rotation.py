import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app.config import Settings
from app.content import ROTATION_MESSAGES, ROTATION_INTERVAL_SECONDS
from app.main import build_dispatcher
from app.storage import Storage

def test_rotation(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Storage(str(tmp_path / "users.db"))
    s.remember_user(123)
    s.enable_registration()
    assert not s.rotation_running()
    s.queue_rotation_for_user(123, now=100)
    assert not s.due_rotation(now=100)
    s.activate_for_known_users(now=100)
    for step in range(len(ROTATION_MESSAGES)):
        now = 100 + step * 600
        row = s.due_rotation(now=now)[0]
        assert row["step"] == step
        s.finish_rotation_job(123, step, row["generation"], now=now)
        assert not s.due_rotation(now=now+599)
        assert s.due_rotation(now=now+600)[0]["step"] == (step + 1) % len(ROTATION_MESSAGES)
    assert Storage(str(tmp_path / "users.db")).due_rotation(now=100 + len(ROTATION_MESSAGES) * 600)[0]["step"] == 0
    s.stop_rotation()
    assert not s.due_rotation(now=99999)
    assert s.known_users() == [123]
    assert ROTATION_INTERVAL_SECONDS == 600
    assert [path for path, _ in ROTATION_MESSAGES] == [
        "assets/hold_spin.jpg", "assets/eternal_diamonds.jpg", "assets/cashback_40.jpg"
    ]

def test_button(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    async def run():
        s = Storage(str(tmp_path / "users.db"))
        s.remember_user(123)
        dp = await build_dispatcher(s, Settings("unused", 99, str(tmp_path / "users.db")))
        handler = next(h.callback for h in dp.callback_query.handlers if h.callback.__name__ == "admin_actions")
        state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock())
        message = SimpleNamespace(chat=SimpleNamespace(type="private"), answer=AsyncMock(), text=None, edit_text=AsyncMock())
        cb = SimpleNamespace(from_user=SimpleNamespace(id=99), data="admin:redirect", message=message, answer=AsyncMock())
        await handler(cb, state)
        assert s.rotation_running()
        cb.data = "admin:broadcast"
        await handler(cb, state)
        assert s.rotation_running()
        assert len(s.due_rotation(now=10**12)) == 1
        cb.data = "admin:reverse"
        await handler(cb, state)
        assert not s.rotation_running() and s.get_mode() == "normal"
        cb.from_user.id = 123
        cb.data = "admin:broadcast"
        await handler(cb, state)
        assert not s.rotation_running()
    asyncio.run(run())
