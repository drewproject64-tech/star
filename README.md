# Star Bot

Python 3.12 + aiogram 3.x Telegram bot with a normal Star menu and an admin-controlled promotion mode.

## Modes

- Normal mode: Promotions, Updates and Submit Promotion remain available in Telegram.
- Admin `REDIRECT` or `/redirect`: enables promotion mode, sends the initial image and registration message to known users, and registers new users who send `/start`.
- Admin `REVERSE` or `/reverse`: returns to normal mode and pauses scheduled promotion delivery. Existing rotation state remains stored so it can resume later.

Admin commands require `ADMIN_ID` to match the administrator's Telegram numeric user ID.

## Promotion assets

The following files are loaded from the repository's `assets/` directory:

- `assets/start.jpg`
- `assets/withdrawal_257000.jpg`
- `assets/withdrawal_320000.jpg`
- `assets/withdrawal_239000.jpg`

After the initial promotion message, the bot sends the configured follow-up after 5 minutes. It then rotates the three withdrawal images at 2-hour intervals per user. The registration button points to the configured URL in `app/content.py`.

The follow-up and captions are defined in `app/content.py`. Ensure any claims or amounts shown in promotional text/images are accurate and authorized before deploying.

## Configuration

Required: `BOT_TOKEN`

Optional: `ADMIN_ID`, `DATABASE_PATH` (defaults to `data/star.db`)

## Run locally

```bash
python -m venv .venv
pip install -r requirements.txt
python -m app.main
```

## Render

This repo includes `render.yaml` for a Render Background Worker and persistent disk. Set `BOT_TOKEN` and `ADMIN_ID` in Render's environment settings. The bot uses polling and removes any existing webhook at startup.
