import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiogram.types import Message
from app.config import Settings
from app.main import broadcast_text, build_dispatcher, send_broadcast_content
from app.storage import Storage


def test_draft_workflow(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)

    async def run():
        storage = Storage(str(tmp_path / 'db'))
        storage.remember_user(123)
        bot = NS(send_message=AsyncMock(), send_photo=AsyncMock())
        state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=99, user_id=99))
        dp = await build_dispatcher(storage, Settings('unused', 99, str(tmp_path / 'db')))
        messages = {h.callback.__name__: h.callback for h in dp.message.handlers}
        callbacks = {h.callback.__name__: h.callback for h in dp.callback_query.handlers}
        m = NS(from_user=NS(id=99), chat=NS(id=99, type='private'), bot=bot,
               answer=AsyncMock(), photo=None, text=None, caption=None, media_group_id=None)
        cb = NS(from_user=m.from_user, message=m, bot=bot, answer=AsyncMock(), data='admin:custombroadcast')
        await callbacks['admin_actions'](cb, state)
        m.photo = [NS(file_id='photo')]
        await messages['broadcast_composer'](m, state)
        old = (await state.get_data())['token']
        m.photo, m.text = None, 'Caption <plain> 🙂'
        await messages['broadcast_composer'](m, state)
        token = (await state.get_data())['token']
        assert token != old
        assert all(c.kwargs['chat_id'] == 99 for c in bot.send_photo.await_args_list)
        before = bot.send_photo.await_count
        cb.data = f'draft:send:{old}'
        await callbacks['confirm_broadcast'](cb, state)
        assert bot.send_photo.await_count == before
        cb.data, cb.from_user = f'draft:send:{token}', NS(id=123)
        await callbacks['confirm_broadcast'](cb, state)
        assert bot.send_photo.await_count == before
        cb.from_user = m.from_user
        await callbacks['confirm_broadcast'](cb, state)
        assert bot.send_photo.await_args.kwargs == dict(chat_id=123, photo='photo', caption='Caption <plain> 🙂', parse_mode=None)
        await callbacks['confirm_broadcast'](cb, state)
        assert bot.send_photo.await_count == before + 1
        # Text first, then photo: preserve text until a photo has its own caption.
        m.text = None
        await messages['send_command'](m, state, CommandObject(command='send', args='Text first'))
        m.photo = [NS(file_id='second-photo')]
        await messages['broadcast_composer'](m, state)
        assert (await state.get_data())['text'] == 'Text first'
        m.caption = 'Attached caption'
        await messages['broadcast_composer'](m, state)
        assert (await state.get_data())['text'] == 'Attached caption'
        cb.data = 'draft:cancel:' + (await state.get_data())['token']
        before = bot.send_photo.await_count
        await callbacks['confirm_broadcast'](cb, state)
        assert await state.get_state() is None
        assert bot.send_photo.await_count == before
        m.photo, m.caption = None, None
        await messages['send_command'](m, state, CommandObject(command='send'))
        m.media_group_id, m.photo = 'album', [NS(file_id='album')]
        await messages['broadcast_composer'](m, state)
        assert not await state.get_data()
        m.media_group_id, m.photo, m.text = None, None, None
        await messages['broadcast_composer'](m, state)
        assert not await state.get_data()
        m.text = 'x' * 4097
        await messages['broadcast_composer'](m, state)
        assert not await state.get_data()
        await messages['admin_command'](m, state)
        assert await state.get_state() is None
    asyncio.run(run())


def test_long_caption_retry_and_blocked_recipient(monkeypatch):
    async def run():
        bot = NS(send_message=AsyncMock(), send_photo=AsyncMock())
        text = '🙂' * 513
        method = SendMessage(chat_id=123, text=text)
        bot.send_message.side_effect = [TelegramRetryAfter(method=method, message='retry', retry_after=1), None]
        monkeypatch.setattr('app.main.asyncio.sleep', AsyncMock())
        await send_broadcast_content(bot, 123, text, 'photo')
        assert bot.send_photo.await_count == 1
        assert bot.send_photo.await_args.kwargs['caption'] is None
        assert bot.send_message.await_count == 2
        bot.send_message.reset_mock(side_effect=True)
        bot.send_photo.reset_mock(side_effect=True)
        bot.send_photo.side_effect = [TelegramForbiddenError(method=method, message='blocked'), None]
        assert await broadcast_text(bot, [0, -1, 123, 456], '', 'photo') == (1, 1)
        bot.send_message.assert_not_awaited()
    asyncio.run(run())


def test_command_accepts_photo_caption():
    async def run():
        msg = Message.model_validate(dict(message_id=1, date=0, chat=dict(id=99, type='private'),
                                         photo=[dict(file_id='photo', file_unique_id='unique', width=1, height=1)],
                                         caption='/send My caption'))
        result = await Command('send')(msg, NS())
        assert result['command'].args == 'My caption'
    asyncio.run(run())
