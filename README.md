# Star Telegram Bot

Python 3.12 and aiogram 3.x, deployed as a Render Background Worker with Telegram polling.

## Modes and commands

- `/start`: saves the user and opens the standard menu in normal mode. In REDIRECT mode, asks users to choose English or Turkish in their private chat.
- `/help`: shows instructions.
- `/admin`: administrator controls, Users & Stats, and Broadcast Message.
- `/send MESSAGE`: admin-only manual text broadcast to saved private-chat users.
- `/redirect` or `REDIRECT`: enables the bilingual flow for new `/start` requests.
- `/reverse` or `REVERSE`: restores the normal menu.

The admin panel's REDIRECT and REVERSE buttons use the same mode behavior.
Ordinary messages do not broadcast unless the admin has deliberately opened the Broadcast Message composer.
The REDIRECT flow asks the user to register, offers the registration link again if needed,
and shows the slot image before the final instructions. Upload the game image as
`assets/redirect_slot.jpg`. If the image is unavailable, the user can retry the Yes button.
After a worker restart, users can use `/start` to begin again. After the final instructions,
users receive a reminder in their chosen language every three hours while REDIRECT is active.
The reminder schedule persists across restarts.

The **Start Game Post Rotation** admin button is still available in REDIRECT mode.
It sends one post every ten minutes in this order: Hold & Spin, Eternal Diamonds, Cashback.
**REVERSE** stops the rotation. **Custom Message** opens the photo/text composer.

## Saved users and data

The existing database schema and all original image assets are retained.
Startup imports `recovered_user_ids.txt` without duplicates; it contains 95 recovered IDs.
Additional live users, statistics, submissions and settings live in the database, not GitHub.
Keep the existing database and use the same Telegram bot identity.
Blocked users cannot receive messages. Run only one polling service per bot token.

Legacy promotion mode is interpreted as registration mode. Legacy scheduled jobs are disabled at startup;
the old text scheduler is removed. The image rotation uses its own persistent job table. Users and submissions are not deleted.

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

## Rotation assets

- `assets/hold_spin.jpg`
- `assets/eternal_diamonds.jpg`
- `assets/cashback_40.jpg`

Progress and next delivery times persist in the configured database. Blocked recipients
are disabled for the current rotation. Starting the rotation again resets it to the first
image. Large audiences and Telegram rate limits can delay deliveries.

## Custom photo and text broadcasts

In your private admin chat, open `/admin` → **Custom Message**, or use `/send`.
Send one photo with a caption, or send photo and text separately in either order.
Text sent during composition replaces the draft caption; a photo without a caption keeps the draft text.
Review the preview and press **Confirm Send** to broadcast to saved users. Nothing is sent before confirmation.
Use **Cancel** or `/admin` to discard the draft. Only the latest preview can be confirmed, once.
`/send MESSAGE` also requires confirmation; `/send MESSAGE` in a photo caption is supported.
Photo-only and text-only drafts work. Albums and other file types are not supported.
Captions over 1,024 Telegram character units are delivered as a separate text message after the photo;
text is limited to 4,096 units. Text is delivered as plain text. Images use Telegram file IDs rather than Render disk space.
Drafts are temporary and are discarded on restart; saved users and the game-post rotation are unaffected.

## Historical account access announcement (16 October 2026)

This section documents the October 16 flow for reference.

The **Send Broadcast — Photos + Notice** admin button queues the entire set immediately
for every saved private chat. The set is: three original withdrawal photos with captions,
then the Turkish account-access notice with the new link. After the whole set is delivered,
that user's next set starts two hours later. Delivery is rate limited; it begins immediately
and takes time to reach all users. Partial progress is saved per user for retries/restarts.
REDIRECT alone and deployment do not activate a new campaign. Existing active jobs resume
from the saved database. REVERSE stops the campaign. `/send` and Custom Message remain
separate special broadcasts, with preview and confirmation.

New /start requests save the user. In REDIRECT mode, /start includes the new notice and
queues the complete set if the broadcast is active. Normal mode keeps the standard menu.
All new redirect /start and rotation buttons use https://strz.ac/CoxW. Already-delivered
Telegram messages are not edited.

Recovered 23 additional IDs from star delivery logs in the last seven days: 95 total.
Logs cannot recover users whose IDs were never logged, settings, submissions or start dates.
Preserve the live database before deployment. Neon migration is still pending.
