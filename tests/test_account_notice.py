import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from app.content import ACCOUNT_ACCESS_MESSAGE, REGISTRATION_URL
from app.main import rotation_scheduler_runner, registration_keyboard
from app.storage import Storage


def test_rotation_sends_account_text_as_fourth_message(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    storage = Storage(str(tmp_path / 'db'))
    storage.remember_user(123)
    storage.activate_for_known_users(now=0)
    for step in range(3):
        row = storage.due_rotation(now=0)[0]
        storage.finish_rotation_job(123, step, row['generation'], now=0)

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


def test_button_only_starts_campaign_and_reverse_stops_it(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    storage = Storage(str(tmp_path / 'db'))
    storage.remember_user(123)
    storage.enable_registration()
    assert not storage.due_rotation(now=10**12)
    storage.activate_for_known_users(now=100)
    for step in range(4):
        row = storage.due_rotation(now=100)[0]
        assert row['step'] == step
        storage.finish_rotation_job(123, step, row['generation'], now=100)
    assert not storage.due_rotation(now=7299)
    assert storage.due_rotation(now=7300)[0]['step'] == 0
    # Existing state survives a restart; new users enter the immediate full set.
    storage = Storage(str(tmp_path / 'db'))
    storage.remember_user(456)
    storage.queue_rotation_for_user(456, now=200)
    assert storage.due_rotation(now=200)[0]['chat_id'] == 456
    storage.stop_rotation()
    assert not storage.due_rotation(now=10**12)
    assert REGISTRATION_URL == 'https://strz.ac/CoxW'
    assert 'Eski bağlantımız artık aktif değil' in ACCOUNT_ACCESS_MESSAGE
