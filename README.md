# Star Bot

Python 3.12 + aiogram 3.x Telegram bot with a normal Star menu and an admin-controlled promotion mode.

## Modes

- Normal mode: Promotions, Updates and Submit Promotion remain available in Telegram.
- Admin `REDIRECT`, `/redirect`, or the admin Enable button: enables promotion mode and queues the current five-message Turkish sequence for all previously recorded private-chat users. Each activation restarts that sequence from message one. Users do not need to send `/start` again. New `/start` requests also receive the sequence.
- Admin `REVERSE` or `/reverse`: returns to normal mode and pauses scheduled promotion delivery. Existing rotation state remains stored so it can resume later.

Admin commands require `ADMIN_ID` to match the administrator's Telegram numeric user ID.

## Manual admin broadcast

In the administrator's private chat with the bot, send:

```
/send hey hi, are you there?
```

Only the text after /send is delivered to previously saved private-chat users. Ordinary messages never trigger a broadcast. Empty /send commands show usage; non-admin users and group chats cannot broadcast. The command works in either mode and does not change the promotion schedule. /redirect and /reverse retain their mode-control behavior. The bot reports delivered and failed totals and rejects another /send while one is running. Blocked or unreachable users are counted as failed; Telegram rate limits are retried. Text is sent as plain text. Broadcasts run in memory and do not resume after a worker restart.

## Promotion assets

The following files are loaded from the repository's `assets/` directory:

- `assets/start.jpg`
- `assets/withdrawal_257000.jpg`
- `assets/withdrawal_320000.jpg`
- `assets/withdrawal_239000.jpg`

The current sequence starts approximately five seconds after activation. The subsequent delays are configured in `NEW_USER_SEQUENCE_DELAYS` in `app/content.py`. The scheduler checks every second and spaces bulk deliveries to limit request bursts; large audiences and Telegram rate limits can increase delivery times. The final message includes `assets/research_final.jpg` when available. Blocked users are disabled after Telegram rejects delivery.\n\nWithdrawal rotation helpers and assets remain in the repository, but the current sequence does not activate the two-hour rotation. Only users retained in the existing SQLite database can be reached.

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

## Persistent PostgreSQL storage

Set `DATABASE_URL` on the active Render worker to the Internal Database URL of
a PostgreSQL database in the same workspace and region. Keep the URL in Render
environment settings, never in GitHub. Without `DATABASE_URL`, SQLite is used.

Startup creates the required tables and imports the recovered recipient list
without duplicates. If a local SQLite file still exists at `DATABASE_PATH`,
its users, mode, schedules and submissions are migrated once. Existing PostgreSQL
rows take precedence. Previously lost SQLite data cannot be reconstructed
except for the recovered IDs committed in this repository.

PostgreSQL persists users and schedules independently of worker restarts.
It does not increase the worker's RAM. SQLite connections are explicitly closed
after every operation; PostgreSQL connections are also closed after use.

Run `python -m pytest tests/test_storage.py` to verify the SQLite backend.
To check the PostgreSQL backend against a disposable test database, set
`TEST_DATABASE_URL` (never a production database).
