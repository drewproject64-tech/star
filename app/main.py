from __future__ import annotations

import asyncio
import html
import logging
import sqlite3
import secrets
from pathlib import Path
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand, CallbackQuery, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.types import FSInputFile

from app.config import Settings
from app.content import (
    ACCOUNT_ACCESS_MESSAGE,
    PROMOTIONS,
    ROTATION_MESSAGES,
    REGISTRATION_CAPTION,
    REGISTRATION_HEADING,
    REGISTRATION_URL,
    START_CAPTION,
    UPDATES,
    Item,
)
from app.keyboards import detail_menu, item_menu, main_menu, result_menu, submit_menu
from app.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("star_bot")
ROOT = Path(__file__).resolve().parent.parent


class BroadcastState(StatesGroup):
    waiting_for_text = State()


class SubmitState(StatesGroup):
    waiting_for_text = State()


def registration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=REGISTRATION_HEADING, url=REGISTRATION_URL)
    ]])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ REDIRECT — Enable", callback_data="admin:redirect")],
        [InlineKeyboardButton(text="⏸ REVERSE — Disable", callback_data="admin:reverse")],
        [InlineKeyboardButton(text="ℹ️ Check Status", callback_data="admin:status")],
        [InlineKeyboardButton(text="👥 Users & Stats", callback_data="admin:users")],
        [InlineKeyboardButton(text="📣 Start Game Post Rotation", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="✍️ Custom Message", callback_data="admin:custombroadcast")],
    ])


def user_stats_text(storage: Storage) -> str:
    stats = storage.user_stats()
    lines = [
        "👥 <b>Users & Stats</b>",
        f"Total saved users: <b>{stats['total']}</b>",
        f"Recovered users: {stats['recovered']}",
        f"Other existing users: {stats['existing']}",
        f"New users since tracking began: {stats['new']}",
        f"New users in last 24 hours: {stats['new_24h']}",
        f"New users in last 7 days: {stats['new_7d']}",
        f"Users who pressed Start in last 24 hours: {stats['active_24h']}",
        "",
        "<b>10 most recent starts (UTC)</b>",
    ]
    for row in stats["recent"]:
        date = datetime.fromtimestamp(row["last_start_at"], timezone.utc).strftime("%d %b %Y %H:%M")
        lines.append(f"<code>{row['chat_id']}</code> | {row['source']} | {date}")
    if not stats["recent"]:
        lines.append("No starts recorded since tracking began.")
    lines.extend(["", "Older start dates are unknown. Saved totals include users who may have blocked the bot."])
    return "\n".join(lines)


def home_text() -> str:
    return (
        "⭐ <b>Star</b>\n\n"
        "Browse information and manage promotion text directly in this chat.\n\n"
        "Choose one of the three functions:\n"
        "📢 Promotions — browse information\n"
        "📰 Updates — read updates\n"
        "✍️ Submit Promotion — submit text for consideration"
    )


def help_text() -> str:
    return (
        "ℹ️ <b>Help</b>\n\n"
        "📢 <b>Promotions:</b> browse an item and read its details.\n"
        "📰 <b>Updates:</b> read information in the chat.\n"
        "✍️ <b>Submit Promotion:</b> send text and receive a reference number.\n\n"
        "Use /start or Main Menu to return home."
    )


def list_text(title: str, items: tuple[Item, ...]) -> str:
    lines = [f"<b>{html.escape(title)}</b>", "", "Choose an item to view its details:"]
    lines.extend(f"{i}. {html.escape(item.title)}" for i, item in enumerate(items, 1))
    return "\n".join(lines)


def item_text(item: Item, index: int, total: int) -> str:
    return f"<b>{html.escape(item.title)}</b>\n\n{html.escape(item.body)}\n\n<i>Item {index + 1} of {total}</i>"


def safe_index(data: str | None, prefix: str, count: int) -> int | None:
    if not data or not data.startswith(f"{prefix}:"):
        return None
    try:
        index = int(data.split(":", 1)[1])
    except (ValueError, TypeError):
        return None
    return index if 0 <= index < count else None


async def send_registration(bot: Bot, chat_id: int) -> None:
    text = f"{START_CAPTION}\n\n{REGISTRATION_CAPTION}"
    image = ROOT / "assets" / "start.jpg"
    if image.is_file():
        await bot.send_photo(chat_id, FSInputFile(image), caption=text, reply_markup=registration_keyboard())
    else:
        await bot.send_message(chat_id, text, reply_markup=registration_keyboard())


def broadcast_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Confirm Send", callback_data=f"draft:send:{token}"),
        InlineKeyboardButton(text="❌ Cancel", callback_data=f"draft:cancel:{token}"),
    ]])


async def send_broadcast_content(bot: Bot, chat_id: int, text: str, photo: str | None = None) -> None:
    """Retry each part independently so a text rate limit doesn't resend the photo."""
    async def retry(method, **kwargs):
        while True:
            try:
                await method(chat_id=chat_id, parse_mode=None, **kwargs)
                return
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)

    # Telegram measures limits in UTF-16 code units, including emoji.
    short_caption = len(text.encode("utf-16-le")) // 2 <= 1024
    if photo:
        await retry(bot.send_photo, photo=photo, caption=text if short_caption else None)
    if text and (not photo or not short_caption):
        await retry(bot.send_message, text=text)


async def broadcast_text(bot: Bot, chat_ids: list[int], text: str, photo: str | None = None) -> tuple[int, int]:
    """Deliver the confirmed draft using Telegram file IDs, without local image storage."""
    sent = failed = 0
    for chat_id in chat_ids:
        if chat_id <= 0:
            continue
        try:
            await send_broadcast_content(bot, chat_id, text, photo)
        except TelegramAPIError:
            failed += 1
            logger.warning("Broadcast delivery failed for chat %s", chat_id, exc_info=True)
        else:
            sent += 1
        await asyncio.sleep(0.05)
    return sent, failed


async def build_dispatcher(storage: Storage, settings: Settings) -> Dispatcher:
    dp = Dispatcher(events_isolation=SimpleEventIsolation())
    broadcast_lock = asyncio.Lock()

    def is_admin(message: Message) -> bool:
        return bool(settings.admin_id and message.from_user and message.from_user.id == settings.admin_id)

    def is_admin_callback(callback: CallbackQuery) -> bool:
        return bool(settings.admin_id and callback.from_user and callback.from_user.id == settings.admin_id)


    async def preview_draft(message: Message, state: FSMContext, text: str, photo: str | None) -> None:
        if len(text.encode("utf-16-le")) // 2 > 4096:
            await message.answer("Please keep broadcast text to 4,096 characters or fewer (emoji may count as two).")
            return
        token = secrets.token_hex(8)
        await state.set_state(BroadcastState.waiting_for_text)
        await state.update_data(text=text, photo=photo, token=token)
        await send_broadcast_content(message.bot, message.chat.id, text, photo)
        await message.answer(
            "Preview only — nothing sent to users yet. Send a photo or replacement caption/text to update this draft, "
            "then tap Confirm Send. /admin cancels. Long captions are sent as a separate message after the photo.",
            reply_markup=broadcast_keyboard(token),
        )


    async def begin_promotion_for_user(bot: Bot, chat_id: int) -> None:
        await send_registration(bot, chat_id)

    async def activate_promotion(message: Message, state: FSMContext) -> None:
        if not is_admin(message):
            await message.answer("This command is only available to the configured administrator.")
            return
        await state.clear()
        count = storage.activate_for_known_users()
        await message.answer(
            f"Rotation started for {count} saved users. The first message is queued now; "
            "the next message follows every 10 minutes. /reverse stops the rotation.",
            reply_markup=admin_keyboard(),
        )

    async def deactivate_promotion(message: Message, state: FSMContext) -> None:
        if not is_admin(message):
            await message.answer("This command is only available to the configured administrator.")
            return
        await state.clear()
        storage.stop_rotation()
        await message.answer("Normal Star mode restored. Promotion scheduling is paused and saved assets remain in the repository.")

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        is_new_user = storage.remember_user(message.chat.id) if message.chat else False
        if message.chat and message.chat.type == "private":
            logger.info("Start recorded for chat %s; new=%s", message.chat.id, is_new_user)
        if storage.get_mode() == "registration":
            # /start is an explicit user action: show the opening message to anyone who requests it.
            try:
                await begin_promotion_for_user(message.bot, message.chat.id)
                storage.queue_rotation_for_user(message.chat.id)
            except (TelegramAPIError, OSError, FileNotFoundError):
                logger.exception("Failed to send registration message")
                await message.answer("The registration message could not be sent right now. Please try again later.")
            return
        await message.answer(home_text(), reply_markup=main_menu(), parse_mode="HTML")

    @dp.message(Command("send"))
    async def send_command(message: Message, state: FSMContext, command: CommandObject) -> None:
        if not is_admin(message):
            await message.answer("This command is only available to the configured administrator.")
            return
        if message.chat.type != "private":
            await message.answer("Use /send in your private chat with the bot.")
            return
        if broadcast_lock.locked():
            await message.answer("A broadcast is already running. Wait for its delivery report before sending another.")
            return
        text = (command.args or "").strip()
        photo = message.photo[-1].file_id if message.photo else None
        if message.media_group_id:
            await message.answer("Send one photo at a time, not an album. Nothing has been broadcast.")
            return
        await state.clear()
        if not text and not photo:
            await state.set_state(BroadcastState.waiting_for_text)
            await message.answer("Send a photo with a caption, a photo and text separately (either order), or text only. "
                                 "You will see a preview before confirming. /admin cancels.")
            return
        await preview_draft(message, state, text, photo)

    @dp.message(Command("admin"))
    async def admin_command(message: Message, state: FSMContext) -> None:
        if not is_admin(message):
            await message.answer("Admin access denied. Set ADMIN_ID in Render to your numeric Telegram user ID, then redeploy.")
            return
        await state.clear()
        await message.answer(
            f"Admin panel\nMode: <b>{html.escape(storage.get_mode().upper())}</b>",
            reply_markup=admin_keyboard(), parse_mode="HTML",
        )

    @dp.callback_query(F.data.startswith("admin:"))
    async def admin_actions(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin_callback(callback):
            await callback.answer("Admin access denied.", show_alert=True)
            return
        action = callback.data.split(":", 1)[1]
        if action == "broadcast":
            if storage.get_mode() != "registration":
                await callback.answer("Enable REDIRECT first.", show_alert=True)
                return
            await state.clear()
            count = storage.activate_for_known_users()
            await callback.answer("Broadcast started")
            if callback.message:
                await callback.message.answer(
                    f"Game post rotation started for {count} saved users. Hold&Spin → Eternal Diamonds. "
                    "Delivery starts now. One game post is sent every 10 minutes, then the rotation repeats. "
                    "REVERSE stops it. Special messages use /send or Custom Message.",
                    reply_markup=admin_keyboard(),
                )
            return
        if action == "custombroadcast":
            if not callback.message or callback.message.chat.type != "private":
                await callback.answer("Use your private chat with the bot.", show_alert=True)
                return
            await state.clear()
            await state.set_state(BroadcastState.waiting_for_text)
            await callback.answer()
            await callback.message.answer(
                "Send a photo with a caption, a photo and text separately (either order), or text only.\n"
                "Review the preview and tap Confirm Send. /admin cancels. /redirect and /reverse remain mode commands."
            )
            return
        await state.clear()
        if action == "redirect":
            count = storage.activate_for_known_users()
            status = f"✅ <b>Rotation started</b>\nFirst message queued for {count} saved users. One message every 10 minutes. /reverse stops it."
        elif action == "reverse":
            storage.stop_rotation()
            status = "⏸ <b>REVERSE enabled</b>\nNormal Star menu restored. Scheduled messages are paused."
        elif action == "users":
            status = user_stats_text(storage)
        elif action == "status":
            status = f"Admin panel\nMode: <b>{html.escape(storage.get_mode().upper())}</b>"
        else:
            await callback.answer("Unknown action.", show_alert=True)
            return
        await callback.answer("Updated")
        if callback.message:
            if callback.message.text != status:
                await callback.message.edit_text(status, reply_markup=admin_keyboard(), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("draft:"))
    async def confirm_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin_callback(callback) or not callback.message or callback.message.chat.type != "private":
            await callback.answer("Admin access denied.", show_alert=True)
            return
        if broadcast_lock.locked():
            await callback.answer("A broadcast is already running.", show_alert=True)
            return
        async with broadcast_lock:
            data = await state.get_data()
            parts = (callback.data or "").split(":")
            if (len(parts) != 3 or parts[1] not in {"send", "cancel"}
                    or await state.get_state() != BroadcastState.waiting_for_text.state
                    or parts[2] != data.get("token")):
                await callback.answer("This preview expired. Use the newest preview or open /admin.", show_alert=True)
                return
            # Consume before delivery: old buttons and duplicate clicks cannot send again.
            await state.clear()
            if parts[1] == "cancel":
                await callback.answer("Cancelled")
                await callback.message.answer("Broadcast cancelled. Nothing sent to users.")
                return
            await callback.answer("Broadcast started")
            recipients = [chat_id for chat_id in storage.known_users() if chat_id > 0]
            await callback.message.answer(f"Broadcast started for {len(recipients)} saved users.")
            sent, failed = await broadcast_text(callback.bot, recipients, data.get("text", ""), data.get("photo"))
            await callback.message.answer(f"Broadcast complete. Delivered: {sent}. Failed: {failed}.")

    @dp.message(Command("help"))
    async def help_command(message: Message, state: FSMContext) -> None:
        await state.clear()
        if storage.get_mode() == "registration":
            await message.answer("Registration mode is active. Use /start to see the registration button.")
            return
        await message.answer(help_text(), reply_markup=main_menu(), parse_mode="HTML")

    @dp.message(Command("redirect"))
    async def redirect_slash(message: Message, state: FSMContext) -> None:
        await activate_promotion(message, state)

    @dp.message(F.text.regexp(r"(?i)^redirect$"))
    async def redirect_plain(message: Message, state: FSMContext) -> None:
        await activate_promotion(message, state)

    @dp.message(Command("reverse"))
    async def reverse_slash(message: Message, state: FSMContext) -> None:
        await deactivate_promotion(message, state)

    @dp.message(F.text.regexp(r"(?i)^reverse$"))
    async def reverse_plain(message: Message, state: FSMContext) -> None:
        await deactivate_promotion(message, state)

    @dp.callback_query(F.data == "home")
    async def home(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if storage.get_mode() == "registration":
            await callback.answer("Registration mode is active.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(home_text(), reply_markup=main_menu(), parse_mode="HTML")

    @dp.callback_query(F.data == "promotions")
    async def promotions(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if storage.get_mode() == "registration":
            await callback.answer("Registration mode is active.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(list_text("📢 Promotions", PROMOTIONS), reply_markup=item_menu("promotion", len(PROMOTIONS)), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("promotion:"))
    async def promotion_item(callback: CallbackQuery) -> None:
        if storage.get_mode() == "registration":
            await callback.answer("Registration mode is active.", show_alert=True)
            return
        index = safe_index(callback.data, "promotion", len(PROMOTIONS))
        if index is None:
            await callback.answer("That option is no longer available.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(item_text(PROMOTIONS[index], index, len(PROMOTIONS)), reply_markup=detail_menu("promotions"), parse_mode="HTML")

    @dp.callback_query(F.data == "updates")
    async def updates(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if storage.get_mode() == "registration":
            await callback.answer("Registration mode is active.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(list_text("📰 Updates", UPDATES), reply_markup=item_menu("update", len(UPDATES)), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("update:"))
    async def update_item(callback: CallbackQuery) -> None:
        if storage.get_mode() == "registration":
            await callback.answer("Registration mode is active.", show_alert=True)
            return
        index = safe_index(callback.data, "update", len(UPDATES))
        if index is None:
            await callback.answer("That option is no longer available.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(item_text(UPDATES[index], index, len(UPDATES)), reply_markup=detail_menu("updates"), parse_mode="HTML")

    @dp.callback_query(F.data == "submit")
    async def submit(callback: CallbackQuery, state: FSMContext) -> None:
        if storage.get_mode() == "registration":
            await callback.answer("Registration mode is active.", show_alert=True)
            return
        await state.set_state(SubmitState.waiting_for_text)
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                "✍️ <b>Submit Promotion</b>\n\nSend the text to submit. Maximum length: 1,000 characters. "
                "Do not include passwords, payment credentials or other private information.",
                reply_markup=submit_menu(), parse_mode="HTML",
            )

    @dp.message(BroadcastState.waiting_for_text)
    async def broadcast_composer(message: Message, state: FSMContext) -> None:
        if not is_admin(message):
            await state.clear()
            return
        if message.chat.type != "private":
            await state.clear()
            return
        if broadcast_lock.locked():
            await message.answer("A broadcast is already running. Wait for its delivery report.")
            return
        if message.media_group_id:
            await message.answer("Send one photo at a time, not an album. Nothing has been broadcast.")
            return
        text = (message.text or message.caption or "").strip()
        if text.startswith("/") or text.lower() in {"redirect", "reverse"}:
            await state.clear()
            await message.answer("Command not broadcast. Open /admin to compose again.")
            return
        data = await state.get_data()
        if message.photo:
            # A separately sent photo keeps the draft text unless it has its own caption.
            photo = message.photo[-1].file_id
            text = text or data.get("text", "")
        elif message.text and text:
            photo = data.get("photo")
        else:
            await message.answer("Please send a photo or text, or /admin to cancel.")
            return
        await preview_draft(message, state, text, photo)

    @dp.message(SubmitState.waiting_for_text)
    async def receive_submission(message: Message, state: FSMContext) -> None:
        if storage.get_mode() == "registration":
            await state.clear()
            await message.answer("Registration mode is active. Normal submissions are paused.")
            return
        text = (message.text or "").strip()
        if not text:
            await message.answer("Please send the submission as text.", reply_markup=submit_menu())
            return
        if len(text) > 1000:
            await message.answer("Please keep the text to 1,000 characters or fewer.", reply_markup=submit_menu())
            return
        try:
            if not message.from_user:
                await message.answer("Unable to identify your Telegram account for this submission.")
                return
            submission_id = storage.add_submission(message.from_user.id, message.from_user.username, text)
        except sqlite3.Error:
            logger.exception("Database error saving submission")
            await message.answer("We couldn't save that submission right now. Please try again.", reply_markup=submit_menu())
            return
        await state.clear()
        await message.answer(
            f"✅ <b>Submission received</b>\n\nReference: <code>ST-{submission_id:06d}</code>\n"
            "Your text has been saved for consideration.",
            reply_markup=result_menu("submit"), parse_mode="HTML",
        )
        if settings.admin_id:
            try:
                await message.bot.send_message(settings.admin_id, f"New submission ST-{submission_id:06d}\nUser ID: {message.from_user.id}\nText: {text}")
            except TelegramAPIError:
                logger.exception("Admin notification failed")

    @dp.errors()
    async def global_error(event: ErrorEvent) -> None:
        logger.exception("Unhandled update error", exc_info=event.exception)
        update = event.update
        callback = getattr(update, "callback_query", None)
        message = getattr(update, "message", None)
        if callback:
            try:
                await callback.answer("Something went wrong. Please try again.", show_alert=True)
            except TelegramAPIError:
                logger.exception("Failed to acknowledge callback")
        elif message:
            try:
                await message.answer("Something went wrong. Use /start to return to the menu.")
            except TelegramAPIError:
                logger.exception("Failed to send error reply")

    @dp.message()
    async def fallback(message: Message, state: FSMContext) -> None:
        if storage.get_mode() == "registration":
            await message.answer("Registration mode is active. Use /start to see the registration button.")
            return
        if await state.get_state() == SubmitState.waiting_for_text:
            await message.answer("Please send submission text, or tap Main Menu to cancel.", reply_markup=submit_menu())
        else:
            await message.answer("Use the menu below or /help to learn about the bot.", reply_markup=main_menu())

    return dp


async def main() -> None:
    settings = Settings.from_env()
    storage = Storage(settings.database_path)
    imported = storage.import_user_ids(ROOT / "recovered_user_ids.txt")
    logger.info("Imported %s recovered users; total saved users: %s", imported, len(storage.known_users()))
    bot = Bot(token=settings.bot_token)
    dp = await build_dispatcher(storage, settings)
    storage.pause_promotions()  # Disable legacy automatic jobs without deleting users or data.
    scheduler_task = asyncio.create_task(rotation_scheduler_runner(bot, storage))
    logger.info("Starting Star bot")
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Open the main menu"),
            BotCommand(command="help", description="Learn how to use the bot"),
            BotCommand(command="admin", description="Open administrator controls"),
            BotCommand(command="send", description="Admin: compose photo or text broadcast"),
            BotCommand(command="redirect", description="Admin: enable registration mode"),
            BotCommand(command="reverse", description="Admin: restore normal mode"),
        ])
        await bot.set_my_short_description("Promotions, updates and text submissions inside Telegram.")
        await bot.set_my_description("A Telegram bot to browse promotion information, read updates and submit promotion text.")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        await asyncio.gather(scheduler_task, return_exceptions=True)
        await bot.session.close()
        logger.info("Star bot stopped")


async def rotation_scheduler_runner(bot: Bot, storage: Storage) -> None:
    while True:
        try:
            if storage.get_mode() == "registration" and storage.rotation_running():
                for row in storage.due_rotation():
                    if storage.get_mode() != "registration" or not storage.rotation_running():
                        break
                    chat_id, step, generation = int(row["chat_id"]), int(row["step"]), int(row["generation"])
                    if not storage.rotation_job_is_current(chat_id, step, generation):
                        continue
                    path, caption = ROTATION_MESSAGES[step % len(ROTATION_MESSAGES)]
                    try:
                        if path:
                            await bot.send_photo(
                                chat_id, FSInputFile(ROOT / path), caption=caption,
                                reply_markup=registration_keyboard(),
                            )
                        else:
                            await bot.send_message(
                                chat_id, caption, reply_markup=registration_keyboard(), parse_mode=None,
                            )
                    except TelegramForbiddenError:
                        storage.disable_rotation_user(chat_id, generation)
                        logger.info("Image rotation disabled for unreachable chat %s", chat_id)
                    except TelegramRetryAfter as exc:
                        storage.retry_rotation_job(chat_id, generation, exc.retry_after)
                        await asyncio.sleep(exc.retry_after)
                    except (TelegramAPIError, OSError):
                        storage.retry_rotation_job(chat_id, generation, 60)
                        logger.warning("Image rotation delivery failed for chat %s", chat_id, exc_info=True)
                    else:
                        storage.finish_rotation_job(chat_id, step, generation)
                        logger.info("Rotation message %s sent to chat %s", step + 1, chat_id)
                    await asyncio.sleep(0.1)
        except Exception:
            logger.exception("Image rotation scheduler error; retrying")
            await asyncio.sleep(5)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
