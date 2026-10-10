from __future__ import annotations

import asyncio
import html
import logging
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, CallbackQuery, ErrorEvent, Message

from app.config import Settings
from app.content import PROMOTIONS, UPDATES, Item
from app.keyboards import detail_menu, item_menu, main_menu, result_menu, submit_menu
from app.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("star_bot")


class SubmitState(StatesGroup):
    waiting_for_text = State()


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


def build_dispatcher(storage: Storage, settings: Settings) -> Dispatcher:
    dp = Dispatcher()

    async def in_promotion_mode() -> bool:
        return storage.get_mode() == "promotion"

    async def reject_during_promotion(message: Message | None = None, callback: CallbackQuery | None = None) -> bool:
        if not await in_promotion_mode():
            return False
        if callback:
            await callback.answer("The bot is temporarily in promotion mode.", show_alert=True)
        elif message:
            await message.answer("The bot is temporarily in promotion mode. Please try again later.")
        return True

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        if await reject_during_promotion(message=message):
            return
        await message.answer(home_text(), reply_markup=main_menu(), parse_mode="HTML")

    @dp.message(Command("help"))
    async def help_command(message: Message, state: FSMContext) -> None:
        await state.clear()
        if await reject_during_promotion(message=message):
            return
        await message.answer(help_text(), reply_markup=main_menu(), parse_mode="HTML")

    @dp.message(Command("redirect"))
    async def redirect_command(message: Message, state: FSMContext) -> None:
        if not settings.admin_id or not message.from_user or message.from_user.id != settings.admin_id:
            await message.answer("This command is only available to the configured administrator.")
            return
        await state.clear()
        storage.set_mode("promotion")
        await message.answer(
            "Promotion mode is enabled. The bot's regular menu is paused.\n"
            "To restore normal mode, send /reverse.\n\n"
            "No promotion message or external destination has been configured yet."
        )

    @dp.message(Command("reverse"))
    async def reverse_command(message: Message, state: FSMContext) -> None:
        if not settings.admin_id or not message.from_user or message.from_user.id != settings.admin_id:
            await message.answer("This command is only available to the configured administrator.")
            return
        await state.clear()
        storage.set_mode("normal")
        await message.answer("Normal mode restored. Send /start to open the menu.")

    @dp.callback_query(F.data == "home")
    async def home(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if await reject_during_promotion(callback=callback):
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(home_text(), reply_markup=main_menu(), parse_mode="HTML")

    @dp.callback_query(F.data == "promotions")
    async def promotions(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if await reject_during_promotion(callback=callback):
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(list_text("📢 Promotions", PROMOTIONS), reply_markup=item_menu("promotion", len(PROMOTIONS)), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("promotion:"))
    async def promotion_item(callback: CallbackQuery) -> None:
        if await reject_during_promotion(callback=callback):
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
        if await reject_during_promotion(callback=callback):
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(list_text("📰 Updates", UPDATES), reply_markup=item_menu("update", len(UPDATES)), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("update:"))
    async def update_item(callback: CallbackQuery) -> None:
        if await reject_during_promotion(callback=callback):
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
        if await reject_during_promotion(callback=callback):
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
        if await reject_during_promotion(message=message):
            await state.clear()
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
        if await reject_during_promotion(message=message):
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
    dp = build_dispatcher(storage, settings)
    logger.info("Starting Star bot")
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Open the main menu"),
            BotCommand(command="help", description="Learn how to use the bot"),
        ])
        await bot.set_my_short_description("Promotions, updates and text submissions inside Telegram.")
        await bot.set_my_description("A Telegram bot to browse promotion information, read updates and submit promotion text.")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Star bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
