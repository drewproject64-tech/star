# Star bot

This repository is initialized with the modular Starz Promosyon bot architecture:
- Python 3.12 and aiogram 3.x
- `app/config.py` for environment configuration
- `app/content.py` for in-chat content
- `app/keyboards.py` for navigation
- `app/storage.py` for SQLite persistence
- `app/main.py` for handlers and polling
- Render Background Worker configuration

Required environment variable: `BOT_TOKEN`. Optional: `ADMIN_ID`, `DATABASE_PATH`.

Install with `pip install -r requirements.txt`; run with `python -m app.main`.

The current repository name was empty before this initialization. Add the intended Starz mode-switching behavior and any required original promotion assets/content before deploying.
