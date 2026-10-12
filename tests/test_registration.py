import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.filters.command import CommandObject
from app.config import Settings
from app.main import build_dispatcher
from app.storage import Storage


def test_registration_reverse_and_manual_broadcast(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    async def exercise():
        storage = Storage(str(tmp_path / "users.db"))
        storage.remember_user(123)
        storage.remember_user(456)
        bot = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock())
        dp = await build_dispatcher(storage, Settings("unused", 99, str(tmp_path / "users.db")))
        handlers = {h.callback.__name__: h.callback for h in dp.message.handlers}
        admin = SimpleNamespace(from_user=SimpleNamespace(id=99),
                                chat=SimpleNamespace(id=99, type="private"),
                                answer=AsyncMock(), bot=bot)
        user = SimpleNamespace(from_user=SimpleNamespace(id=123),
                               chat=SimpleNamespace(id=123, type="private"),
                               answer=AsyncMock(), bot=bot)
        await handlers["redirect_slash"](admin, state)
        assert storage.get_mode() == "registration"
        assert set(storage.known_users()) == {123, 456}
        assert not storage.due_sequences(now=10**12)
        bot.send_message.assert_not_awaited()
        bot.send_photo.assert_not_awaited()

        await handlers["start"](user, state)
        calls = bot.send_message.await_args_list + bot.send_photo.await_args_list
        assert len(calls) == 1
        button = calls[0].kwargs["reply_markup"].inline_keyboard[0][0]
        assert button.url
        assert not storage.due_sequences(now=10**12)

        await handlers["reverse_slash"](admin, state)
        assert storage.get_mode() == "normal"
        await handlers["start"](user, state)
        assert "Star" in user.answer.await_args.args[0]
        before = bot.send_message.await_count
        await handlers["send_command"](admin, state, CommandObject(command="send", args="Custom text"))
        assert bot.send_message.await_count - before == 2
        assert {c.args[0] for c in bot.send_message.await_args_list[-2:]} == {123, 456}
        assert all(c.args[1] == "Custom text" for c in bot.send_message.await_args_list[-2:])
        await handlers["redirect_slash"](user, state)
        assert storage.get_mode() == "normal", "Non-admin changed mode"
        assert set(storage.known_users()) == {123, 456}

    asyncio.run(exercise())


def test_legacy_mode_and_saved_ids_are_preserved(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    storage = Storage(str(tmp_path / "legacy.db"))
    storage.remember_user(8647561557)
    with storage._connect() as connection:
        connection.execute("INSERT INTO bot_settings(key, value) VALUES('mode', 'promotion')")
    assert Storage(str(tmp_path / "legacy.db")).get_mode() == "registration"
    assert storage.known_users() == [8647561557]
