import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from app import redirect


@pytest.mark.parametrize("language", ["en", "tr"])
def test_redirect_registration_and_game(tmp_path, monkeypatch, language):
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
            await redirect.handle_redirect(callback, state)
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
        assert posted[-1][1].inline_keyboard[0][0].url == redirect.REGISTER_URL

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

    asyncio.run(exercise())
