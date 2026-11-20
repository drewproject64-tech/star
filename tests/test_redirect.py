import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from app import redirect
from app.storage import Storage


@pytest.mark.parametrize("language", ["en", "tr"])
def test_redirect_registration_and_game(tmp_path, monkeypatch, language):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr("app.storage.time", SimpleNamespace(time=lambda: clock.now))
    storage = Storage(str(tmp_path / "star.db"))
    storage.enable_registration()

    async def exercise():
        slot_image = tmp_path / "redirect_slot.jpg"
        monkeypatch.setattr(redirect, "SLOT_IMAGE", slot_image)
        posted = []

        async def send(self, content, **kwargs):
            posted.append((content, kwargs.get("reply_markup")))
            return self.model_copy(update={"message_id": len(posted)})

        monkeypatch.setattr(Message, "answer", send)
        monkeypatch.setattr(Message, "answer_photo", send)
        delete = AsyncMock()
        monkeypatch.setattr(Message, "delete", delete)
        command = Message.model_validate({
            "message_id": 100,
            "date": 0,
            "chat": {"id": 42, "type": "private"},
        })
        state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=42, user_id=42))
        bot = SimpleNamespace(delete_message=AsyncMock())

        async def click(action, message_id):
            callback = SimpleNamespace(
                data=f"redirect:{action}",
                message=command.model_copy(update={"message_id": message_id}),
                bot=bot,
                answer=AsyncMock(),
            )
            await redirect.handle_redirect(callback, state, storage)
            return callback

        await redirect.prompt_for_language(command, state)
        assert [button.text for button in posted[0][1].inline_keyboard[0]] == ["English", "Türkçe"]
        await click(language, 1)
        delete.assert_awaited_once()
        copy = redirect.COPY[language]
        assert [content for content, _ in posted[1:4]] == [
            copy.prize, copy.register_prompt, copy.registered_prompt,
        ]
        await click("no", 4)
        assert posted[-1][1].inline_keyboard[0][0].url == "https://strz.ac/CoxW"

        missing = await click("yes", 4)
        missing.answer.assert_awaited_once_with(copy.image_unavailable, show_alert=True)
        bot.delete_message.assert_not_awaited()
        slot_image.touch()
        await click("yes", 4)
        assert [call.args for call in bot.delete_message.await_args_list] == [
            (42, 2), (42, 3), (42, 4), (42, 5),
        ]
        assert posted[5][0] == copy.game_intro
        assert posted[6][0].path == slot_image
        assert posted[7][0] == copy.find_prompt
        await click("found", 8)
        assert posted[-1][0] == copy.final_message
        await click("found", 8)
        assert len(posted) == 9

        clock.now += 3 * 60 * 60 - 1
        assert not storage.due_redirect_reminders()
        clock.now += 1
        reopened = Storage(str(tmp_path / "star.db"))
        row, = reopened.due_redirect_reminders()
        lease = reopened.claim_redirect_reminder(42, row["next_at"])
        assert row["language"] == language and lease is not None
        assert storage.claim_redirect_reminder(42, row["next_at"]) is None
        reopened.finish_redirect_reminder(42, lease, 0)

        bot.send_message = AsyncMock()
        monkeypatch.setattr(redirect, "asyncio", SimpleNamespace(
            sleep=AsyncMock(side_effect=asyncio.CancelledError())
        ))
        with pytest.raises(asyncio.CancelledError):
            await redirect.redirect_reminder_runner(bot, reopened)
        bot.send_message.assert_awaited_once_with(42, copy.reminder, reply_markup=redirect.registration_link(copy))
        assert not storage.due_redirect_reminders()
        clock.now += 3 * 60 * 60
        assert len(storage.due_redirect_reminders()) == 1
        storage.stop_rotation()
        assert not storage.due_redirect_reminders()

    asyncio.run(exercise())
