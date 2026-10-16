import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from app.content import ACCOUNT_ACCESS_MESSAGE, ACCOUNT_CAMPAIGN_ID, REGISTRATION_URL
from app.main import deliver_account_notices, rotation_scheduler_runner, registration_keyboard
from app.storage import Storage


def test_notice_persists_and_new_users_are_included(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    path = str(tmp_path / 'db')
    storage = Storage(path)
    for chat in (123, 456, 789):
        storage.remember_user(chat)
    storage.queue_account_notice(ACCOUNT_CAMPAIGN_ID, now=0)
    method = SendMessage(chat_id=456, text='test')

    async def run():
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=[None,
            TelegramForbiddenError(method=method, message='blocked'),
            TelegramRetryAfter(method=method, message='retry', retry_after=5)]))
        monkeypatch.setattr('app.main.asyncio.sleep', AsyncMock())
        await deliver_account_notices(bot, storage)
        assert bot.send_message.await_count == 3
        assert all(c.args[1] == ACCOUNT_ACCESS_MESSAGE for c in bot.send_message.await_args_list)
        assert bot.send_message.await_args_list[0].kwargs['reply_markup'].inline_keyboard[0][0].url == REGISTRATION_URL
    asyncio.run(run())
    reopened = Storage(path)
    reopened.queue_account_notice(ACCOUNT_CAMPAIGN_ID, now=0)
    assert [r['chat_id'] for r in reopened.due_account_notices(ACCOUNT_CAMPAIGN_ID, now=10**12)] == [789]
    reopened.remember_user(999)
    reopened.queue_account_notice(ACCOUNT_CAMPAIGN_ID, now=0)
    assert {r['chat_id'] for r in reopened.due_account_notices(ACCOUNT_CAMPAIGN_ID, now=10**12)} == {789, 999}
    reopened.finish_account_notice(ACCOUNT_CAMPAIGN_ID, 999)  # registration /start delivered it
    assert {r['chat_id'] for r in reopened.due_account_notices(ACCOUNT_CAMPAIGN_ID, now=10**12)} == {789}
    assert 'Eski bağlantımız artık aktif değil' in ACCOUNT_ACCESS_MESSAGE
    assert REGISTRATION_URL == 'https://strz.ac/CoxW'


def test_rotation_sends_account_text_as_fourth_message(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    storage = Storage(str(tmp_path / 'db'))
    storage.remember_user(123)
    storage.activate_for_known_users(now=0)
    for step in range(3):
        row = storage.due_rotation(now=step*7200)[0]
        storage.finish_rotation_job(123, step, row['generation'], now=step*7200)

    async def run():
        bot = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock())
        monkeypatch.setattr('app.main.asyncio.sleep', AsyncMock(side_effect=asyncio.CancelledError()))
        try:
            await rotation_scheduler_runner(bot, storage)
        except asyncio.CancelledError:
            pass
        bot.send_photo.assert_not_awaited()
        bot.send_message.assert_awaited_once_with(123, ACCOUNT_ACCESS_MESSAGE,
            reply_markup=registration_keyboard(), parse_mode=None)
    asyncio.run(run())
    with storage._connect() as c:
        assert c.execute('SELECT step FROM rotation_jobs WHERE chat_id=123').fetchone()['step'] == 0
