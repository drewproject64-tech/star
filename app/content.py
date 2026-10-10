from dataclasses import dataclass

REGISTRATION_URL = "https://strz.cc/CoxW"
REGISTRATION_HEADING = "✨✨ 𝑩𝑼𝑹𝑨𝑫𝑨𝑵 𝑲𝑨𝒀𝑰𝑻 𝑶𝑳 ✨✨"
REGISTRATION_CAPTION = "Kayıt olmak için aşağıdaki butona dokunun."
START_CAPTION = "🌟 Starz'a hoş geldiniz! Güncel kampanya bilgilerini ve kayıt seçeneklerini aşağıdan inceleyebilirsiniz."
BONUS_FOLLOWUP = (
    "💵 Even a smaller number can trigger a fast tap.\n"
    "Your $250 bonus is right there — ready to turn into a strong start."
)
WITHDRAWAL_IMAGES = (
    ("assets/withdrawal_257000.jpg", "💬 Paylaşılan çekim görseli: 257.000 TL"),
    ("assets/withdrawal_320000.jpg", "💬 Paylaşılan çekim görseli: 320.000 TL"),
    ("assets/withdrawal_239000.jpg", "💬 Paylaşılan çekim görseli: 239.000 TL"),
)
PROMOTION_INTERVAL_SECONDS = 2 * 60 * 60
BONUS_DELAY_SECONDS = 5 * 60


@dataclass(frozen=True)
class Item:
    title: str
    body: str


# Replace sample material with accurate, current content before production use.
PROMOTIONS = (
    Item("Featured Promotion", "Present the offer, eligibility, validity period and key terms here."),
    Item("Campaign Information", "Provide a clear campaign summary, including its conditions and intended audience."),
    Item("Promotion Guidelines", "Use accurate, relevant text. Do not include passwords, payment credentials or other private information."),
)

UPDATES = (
    Item("Latest Update", "Read the latest information directly in this bot."),
    Item("How It Works", "Browse promotion information, read updates and submit text from within this chat."),
    Item("Submission Status", "Each accepted submission is saved and assigned a reference number."),
)
