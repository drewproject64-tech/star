from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_id: int | None
    database_path: str

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN environment variable is required")

        raw_admin = os.getenv("ADMIN_ID", "").strip()
        try:
            admin_id = int(raw_admin) if raw_admin else None
        except ValueError as exc:
            raise RuntimeError("ADMIN_ID must be a numeric Telegram user ID") from exc

        database_path = os.getenv("DATABASE_PATH", "data/star.db").strip() or "data/star.db"
        return cls(token, admin_id, database_path)
