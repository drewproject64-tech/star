# Star Telegram Bot

Python 3.12 and aiogram 3.x, deployed as a Render Background Worker with Telegram polling.

## Modes and commands

- `/start`: saves the user and opens the standard menu in normal mode. In registration mode, shows the original start image, registration text, and registration button.
- `/help`: shows instructions.
- `/admin`: administrator controls, Users & Stats, and Broadcast Message.
- `/send MESSAGE`: admin-only manual text broadcast to saved private-chat users.
- `/redirect` or `REDIRECT`: enables registration mode. It does not broadcast to saved users or run an automatic message sequence.
- `/reverse` or `REVERSE`: restores the normal menu.

The admin panel's REDIRECT and REVERSE buttons use the same mode behavior.
Ordinary messages do not broadcast unless the admin has deliberately opened the Broadcast Message composer.
The 10-minute rotating broadcast schedule is pending and is not implemented.

## Saved users and data

The existing database schema and all original image assets are retained.
Startup imports `recovered_user_ids.txt` without duplicates; it contains 72 recovered IDs.
Additional live users, statistics, submissions and settings live in the database, not GitHub.
Keep the existing database and use the same Telegram bot identity.
Blocked users cannot receive messages. Run only one polling service per bot token.

Legacy promotion mode is interpreted as registration mode. Legacy scheduled jobs are disabled at startup;
there is no automatic scheduler. Users and submissions are not deleted.

## Configuration

- `BOT_TOKEN`: required Telegram bot token.
- `ADMIN_ID`: administrator's numeric Telegram user ID.
- `DATABASE_PATH`: SQLite file, default `data/star.db`; persistent Render disk path `/data/star.db`.
- `DATABASE_URL`: optional PostgreSQL connection URL. Existing PostgreSQL support is retained. When set, it takes precedence over SQLite.

Keep secrets in Render environment settings, never in GitHub.
SQLite needs a persistent disk to survive redeploys. PostgreSQL persists independently of the worker.
If a local SQLite file survives at DATABASE_PATH, its data is migrated once to PostgreSQL.
This code update does not switch or migrate the live database by itself.

## Deployment

Build: `pip install -r requirements.txt`
Start: `python -m app.main`

Keep BOT_TOKEN, ADMIN_ID and existing database configuration unchanged.
Render services connected to main may automatically deploy this update.

## Verification

`python -m pytest -q tests`

Registration/reverse behavior, saved users, manual broadcasts and SQLite connection closing are tested.
The PostgreSQL migration test requires TEST_DATABASE_URL pointing to a disposable test database.
