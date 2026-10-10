from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Promotions", callback_data="promotions")],
        [InlineKeyboardButton(text="📰 Updates", callback_data="updates")],
        [InlineKeyboardButton(text="✍️ Submit Promotion", callback_data="submit")],
    ])


def item_menu(prefix: str, count: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"View {i + 1}", callback_data=f"{prefix}:{i}")] for i in range(count)]
    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def detail_menu(list_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data=list_callback)],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")],
    ])


def result_menu(retry_callback: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if retry_callback:
        rows.append([InlineKeyboardButton(text="🔁 Run Again", callback_data=retry_callback)])
    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def submit_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")]])
