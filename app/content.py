from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    title: str
    body: str


# Replace sample material with accurate, approved content before production use.
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

# Set these to the exact promotion copy and asset links approved for this bot.
# Do not invent registration or withdrawal claims. If enabled, use only destinations
# and content you are authorized to publish.
PROMOTION_INTERVAL_SECONDS = 2 * 60 * 60
