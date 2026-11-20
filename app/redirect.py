import logging
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)
SLOT_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "redirect_slot.jpg"
REGISTER_URL = (
    "https://starzbet584.com/tr-tr/play-game/3ccbcd0d-6274-47d7-8749-a3cc1652f895"
    "?mode=preview&tid=AAJrAHMwQ294VwR9UHd7Fnae7IsFTw"
)


@dataclass(frozen=True)
class RedirectCopy:
    prize: str
    register_prompt: str
    register_button: str
    registered_prompt: str
    yes_button: str
    no_button: str
    game_intro: str
    find_prompt: str
    found_button: str
    image_unavailable: str
    final_message: str


COPY = {
    "en": RedirectCopy(
        prize="You’re one click away from winning ₺50,000!",
        register_prompt="Click the button below to register.",
        register_button="Register to play",
        registered_prompt="Have you registered? Then I can send you the game to play to win ₺50,000.",
        yes_button="Yes, let’s play",
        no_button="No, I haven’t",
        game_intro="This is the slot machine to play.",
        find_prompt="Once you find it, click the button below to proceed.",
        found_button="Found it",
        image_unavailable="The slot-machine image is currently unavailable. Please try again later.",
        final_message=(
            "Deposit ₺100.\n\n"
            "Then bet twice with just ₺1 each time.\n\n"
            "Wait for 5 seconds and bet ₺1.50, which will unlock God Mode on the machine.\n\n"
            "Enjoy and win now!"
        ),
    ),
    "tr": RedirectCopy(
        prize="₺50.000 kazanmaya bir tık uzaktasınız!",
        register_prompt="Kayıt olmak için aşağıdaki düğmeye tıklayın.",
        register_button="Oynamak için kayıt ol",
        registered_prompt="Kayıt oldunuz mu? Olduysanız ₺50.000 kazanmak için oynayacağınız oyunu size gönderebilirim.",
        yes_button="Evet, oynayalım",
        no_button="Hayır, henüz kayıt olmadım",
        game_intro="Oynayacağınız slot makinesi bu.",
        find_prompt="Bulduğunuzda devam etmek için aşağıdaki düğmeye tıklayın.",
        found_button="Buldum",
        image_unavailable="Slot makinesi görseli şu anda kullanılamıyor. Lütfen daha sonra tekrar deneyin.",
        final_message=(
            "₺100 yatırın.\n\n"
            "Ardından her seferinde sadece ₺1 ile iki kez bahis yapın.\n\n"
            "5 saniye bekleyin ve ₺1,50 bahis yapın. Böylece makinede Tanrı Modu açılacak.\n\n"
            "Keyfini çıkarın ve hemen kazanın!"
        ),
    ),
}


def buttons(*choices: tuple[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=f"redirect:{action}")
        for label, action in choices
    ]])


async def prompt_for_language(message: Message, state: FSMContext) -> None:
    prompt = await message.answer(
        "Choose your language.\nDilinizi seçin.",
        reply_markup=buttons(("English", "en"), ("Türkçe", "tr")),
    )
    await state.update_data(redirect_stage="language", redirect_prompt=prompt.message_id)


async def registration_prompt(message: Message, copy: RedirectCopy) -> Message:
    return await message.answer(
        copy.register_prompt,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=copy.register_button, url=REGISTER_URL)
        ]]),
    )


async def handle_redirect(callback: CallbackQuery, state: FSMContext) -> None:
    message = callback.message
    data = await state.get_data()
    action = callback.data.split(":", 1)[1]
    stage = data.get("redirect_stage")
    if not isinstance(message, Message) or data.get("redirect_prompt") != message.message_id:
        await callback.answer("Use /start to begin again. / Yeniden başlamak için /start kullanın.", show_alert=True)
        return

    if stage == "language" and action in COPY:
        copy = COPY[action]
        await callback.answer()
        with suppress(TelegramBadRequest):
            await message.delete()
        prize = await message.answer(copy.prize)
        link = await registration_prompt(message, copy)
        question = await message.answer(
            copy.registered_prompt,
            reply_markup=buttons((copy.yes_button, "yes"), (copy.no_button, "no")),
        )
        await state.update_data(
            redirect_stage="registration",
            redirect_language=action,
            redirect_prompt=question.message_id,
            redirect_messages=[prize.message_id, link.message_id, question.message_id],
        )
        return

    copy = COPY.get(data.get("redirect_language"))
    if copy and stage == "registration" and action == "no":
        await callback.answer()
        reminder = await registration_prompt(message, copy)
        await state.update_data(redirect_messages=[*data["redirect_messages"], reminder.message_id])
    elif copy and stage == "registration" and action == "yes":
        if not SLOT_IMAGE.is_file():
            logger.warning("Redirect image missing at %s", SLOT_IMAGE)
            await callback.answer(copy.image_unavailable, show_alert=True)
            return
        await callback.answer()
        for message_id in data["redirect_messages"]:
            with suppress(TelegramBadRequest):
                await callback.bot.delete_message(message.chat.id, message_id)
        await message.answer(copy.game_intro)
        await message.answer_photo(FSInputFile(SLOT_IMAGE))
        prompt = await message.answer(copy.find_prompt, reply_markup=buttons((copy.found_button, "found")))
        await state.update_data(redirect_stage="game", redirect_prompt=prompt.message_id)
    elif copy and stage == "game" and action == "found":
        await callback.answer()
        await message.answer(copy.final_message)
        await state.clear()
    else:
        await callback.answer("Use /start to begin again. / Yeniden başlamak için /start kullanın.", show_alert=True)
