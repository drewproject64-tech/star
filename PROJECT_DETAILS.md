# Project details: Star registration update

Target repository: https://github.com/drewproject64-tech/star
Related repository mentioned in the supplied brief: https://github.com/drewproject64-tech/newpromo

This update applies to star only. It preserves saved users, the recovered-ID file,
the normal menu, admin statistics, manual broadcasts, image assets and existing database support.

REDIRECT enables registration mode. /start displays the registration image and button.
REVERSE restores the normal menu.
The old automatic message sequence and scheduler have been removed.
A rotating broadcast at 10-minute intervals remains pending.

The standard runtime is Python 3.12, aiogram 3.x and Telegram polling.
Build command: pip install -r requirements.txt
Start command: python -m app.main

Required configuration: BOT_TOKEN
Admin configuration: ADMIN_ID
SQLite configuration: DATABASE_PATH (default data/star.db; persistent Render disk /data/star.db)
Optional existing PostgreSQL configuration: DATABASE_URL

Only the 72 recovered IDs are included in GitHub. Additional users require keeping
or migrating the actual database. No user IDs or image assets are changed by this update.
This update does not switch the live Render service or its database settings.
Run only one polling service for the same Telegram bot token.
