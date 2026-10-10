from __future__ import annotations

import asyncio
import html
import logging
import sqlite3
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, CallbackQuery, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.types import FSInputFile

from app.config import Settings
from app.content import (
    BONUS_DELAY_SECONDS,
    BONUS_FOLLOWUP,
    PROMOTION_INTERVAL_SECONDS,
    PROMOTIONS,
    REGISTRATION_CAPTION,
    REGISTRATION_HEADING,
    REGISTRATION_URL,
    START_CAPTION,
    WITHDRAWAL_IMAGES,
    Item,
)
from app.keyboards import detail_menu, item_menu, main_menu, result_menu, submit_menu
from app.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("star_bot")
ROOT = Path(__file__).resolve().parent.parent


class SubmitState(StatesGroup):
    waiting_for_text = State()


def registration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✨ 𝑩𝑼𝑹𝑨𝑫𝑨𝑵 𝑲𝑨𝒀𝑰𝑻 𝑶𝑳 ✨", url=REGISTRATION_URL)
    ]])


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


async def send_promotion_start(bot: Bot, chat_id: int) -> None:
    start_image = ROOT / "assets" / "start.jpg"
    if not start_image.is_file():
        raise FileNotFoundError(f"Required promotion image not found: {start_image}")
    await bot.send_photo(chat_id, FSInputFile(start_image), caption=START_CAPTION)
    await bot.send_message(
        chat_id,
        f"{REGISTRATION_HEADING}\n\n{REGISTRATION_CAPTION}",
        reply_markup=registration_keyboard(),
    )


async def send_withdrawal(bot: Bot, chat_id: int, step: int) -> int:
    index = step % len(WITHDRAWAL_IMAGES)
    relative_path, caption = WITHDRAWAL_IMAGES[index]
    image_path = ROOT / relative_path
    if not image_path.is_file():
        raise FileNotFoundError(f"Required promotion image not found: {image_path}")
    await bot.send_photo(
        chat_id,
        FSInputFile(image_path),
        caption=caption,
        reply_markup=registration_keyboard(),
    )
    return (index + 1) % len(WITHDRAWAL_IMAGES)


async def build_dispatcher(storage: Storage, settings: Settings) -> Dispatcher:
    dp = Dispatcher()

    def is_admin(message: Message) -> bool:
        return bool(settings.admin_id and message.from_user and message.from_user.id == settings.admin_id)

    async def promotion_scheduler(bot: Bot) -> None:
        while True:
            if storage.get_mode() == "promotion":
                for chat_id in storage.due_bonuses():
                    try:
                        await bot.send_message(chat_id, BONUS_FOLLOWUP)
                        storage.mark_bonus_sent(chat_id)
                    except TelegramAPIError:
                        logger.warning("Could not send five-minute follow-up to chat %s", chat_id, exc_info=True)
                        storage.mark_bonus_sent(chat_id)
                for row in storage.due_promotions():
                    chat_id = int(row["chat_id"])
                    try:
                        next_step = await send_withdrawal(bot, chat_id, int(row["withdrawal_step"]))
                        storage.mark_promotion_sent(chat_id, next_step)
                    except (TelegramAPIError, OSError, FileNotFoundError):
                        logger.warning("Could not send scheduled image to chat %s", chat_id, exc_info=True)
                        # Retry on the next interval rather than looping rapidly.
                        storage.mark_promotion_sent(chat_id, (int(row["withdrawal_step"]) + 1) % len(WITHDRAWAL_IMAGES))
            await asyncio.sleep(30)

    async def begin_promotion_for_user(bot: Bot, chat_id: int) -> None:
        await send_promotion_start(bot, chat_id)
        storage.enable_promotion_for_user(chat_id)

    async def activate_promotion(message: Message, state: FSMContext) -> None:
        if not is_admin(message):
            await message.answer("This command is only available to the configured administrator.")
            return
        await state.clear()
        storage.set_mode("promotion")
        users = storage.known_users()
        sent = 0
        failed = 0
        for chat_id in users:
            try:
                await begin_promotion_for_user(message.bot, chat_id)
                sent += 1
            except (TelegramAPIError, OSError, FileNotFoundError):
                failed += 1
                logger.warning("Could not start promotion for chat %s", chat_id, exc_info=True)
        await message.answer(
            f"Promotion mode enabled. Initial promotion sent to {sent} known chat(s); "
            f"{failed} failed. New /start users will receive it too. "
            "The follow-up is scheduled after 5 minutes, then withdrawal images rotate every 2 hours. "
            "Send REVERSE to pause promotions and restore the Star menu."
        )

    async def deactivate_promotion(message: Message, state: FSMContext) -> None:
        if not is_admin(message):
            await message.answer("This command is only available to the configured administrator.")
            return
        await state.clear()
        storage.set_mode("normal")
        storage.pause_promotions()
        await message.answer("Normal Star mode restored. Promotion scheduling is paused and saved assets remain in the repository.")

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        if message.chat:
            storage.remember_user(message.chat.id)
        if storage.get_mode() == "promotion":
            try:
                await begin_promotion_for_user(message.bot, message.chat.id)
            except (TelegramAPIError, OSError, FileNotFoundError):
                logger.exception("Failed to send initial promotion")
                await message.answer("The promotion message could not be sent right now. Please try again later.")
            return
        await message.answer(home_text(), reply_markup=main_menu(), parse_mode="HTML")

    @dp.message(Command("help"))
    async def help_command(message: Message, state: FSMContext) -> None:
        await state.clear()
        if storage.get_mode() == "promotion":
            await message.answer("Promotion mode is active. Use the registration button in the promotion message.")
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
        if storage.get_mode() == "promotion":
            await callback.answer("Promotion mode is active.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(home_text(), reply_markup=main_menu(), parse_mode="HTML")

    @dp.callback_query(F.data == "promotions")
    async def promotions(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if storage.get_mode() == "promotion":
            await callback.answer("Promotion mode is active.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(list_text("📢 Promotions", PROMOTIONS), reply_markup=item_menu("promotion", len(PROMOTIONS)), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("promotion:"))
    async def promotion_item(callback: CallbackQuery) -> None:
        if storage.get_mode() == "promotion":
            await callback.answer("Promotion mode is active.", show_alert=True)
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
        if storage.get_mode() == "promotion":
            await callback.answer("Promotion mode is active.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(list_text("📰 Updates", UPDATES), reply_markup=item_menu("update", len(UPDATES)), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("update:"))
    async def update_item(callback: CallbackQuery) -> None:
        if storage.get_mode() == "promotion":
            await callback.answer("Promotion mode is active.", show_alert=True)
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
        if storage.get_mode() == "promotion":
            await callback.answer("Promotion mode is active.", show_alert=True)
            return
        await state.set_state(SubmitState.waiting_for_text)
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                "✍️ <b>Submit Promotion</b>\n\nSend the text to submit. Maximum length: 1,000 characters. "
                "Do not include passwords, payment credentials or other private information.",
                reply_markup=submit_menu(), parse_mode="HTML",
            )

    @dp.message(SubmitState.waiting_for_text)
    async def receive_submission(message: Message, state: FSMContext) -> None:
        if storage.get_mode() == "promotion":
            await state.clear()
            await message.answer("Promotion mode is active. Normal submissions are paused.")
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
        if storage.get_mode() == "promotion":
            await message.answer("Promotion mode is active. Use the registration button in the promotion message.")
            return
        if await state.get_state() == SubmitState.waiting_for_text:
            await message.answer("Please send submission text, or tap Main Menu to cancel.", reply_markup=submit_menu())
        else:
            await message.answer("Use the menu below or /help to learn about the bot.", reply_markup=main_menu())

    return dp


async def main() -> None:
    settings = Settings.from_env()
    storage = Storage(settings.database_path)
    bot = Bot(token=settings.bot_token)
    dp = await build_dispatcher(storage, settings)
    scheduler_task = asyncio.create_task(promotion_scheduler_runner(bot, storage))
    logger.info("Starting Star bot")
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Open the main menu"),
            BotCommand(command="help", description="Learn how to use the bot"),
            BotCommand(command="redirect", description="Admin: enable promotion mode"),
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


async def promotion_scheduler_runner(bot: Bot, storage: Storage) -> None:
    while True:
        if storage.get_mode() == "promotion":
            for chat_id in storage.due_bonuses():
                try:
                    await bot.send_message(chat_id, BONUS_FOLLOWUP)
                except TelegramAPIError:
                    logger.warning("Could not send five-minute follow-up to chat %s", chat_id, exc_info=True)
                finally:
                    storage.mark_bonus_sent(chat_id)
            for row in storage.due_promotions():
                chat_id = int(row["chat_id"])
                step = int(row["withdrawal_step"])
                try:
                    index = step % len(WITHDRAWAL_IMAGES)
                    relative_path, caption = WITHDRAWAL_IMAGES[index]
                    image_path = ROOT / relative_path
                    if not image_path.is_file():
                        raise FileNotFoundError(f"Required promotion image not found: {image_path}")
                    await bot.send_photo(chat_id, FSInputFile(image_path), caption=caption, reply_markup=registration_keyboard())
                    next_step = (index + 1) % len(WITHDRAWAL_IMAGES)
                except (TelegramAPIError, OSError, FileNotFoundError):
                    logger.warning("Could not send scheduled image to chat %s", chat_id, exc_info=True)
                    next_step = (step + 1) % len(WITHDRAWAL_IMAGES)
                finally:
                    storage.mark_promotion_sent(chat_id, next_step)
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
