# Star Telegram Bot

Python 3.12 and aiogram 3.x, deployed as a Render Background Worker with Telegram polling.

## Modes and commands

- `/start`: saves the user and opens the standard menu in normal mode. In registration mode, shows the original start image, registration text, and registration button.
- `/help`: shows instructions.
- `/admin`: administrator controls, Users & Stats, and Broadcast Message.
- `/send MESSAGE`: admin-only manual text broadcast to saved private-chat users.
- `/redirect` or `REDIRECT`: enables registration mode and waits for the administrator to tap Send Broadcast.
- `/reverse` or `REVERSE`: restores the normal menu.

The admin panel's REDIRECT and REVERSE buttons use the same mode behavior.
Ordinary messages do not broadcast unless the admin has deliberately opened the Broadcast Message composer.
In registration mode, tap **Send Broadcast** to start the configured four-message rotation for saved users. The first image is queued immediately; later images follow 2 hours after each successful delivery. Order: 257,000 TL, 320,000 TL, 239,000 TL, account-access notice, then repeat. New users who start during an active rotation are included. REVERSE stops it. **Custom Message** opens the photo/text composer; `/send MESSAGE` previews a text draft and `/send` opens an empty composer.

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

- `assets/withdrawal_257000.jpg`
- `assets/withdrawal_320000.jpg`
- `assets/withdrawal_239000.jpg`

Captions are Turkish and describe the supplied images. No recurring two-hour expiry claim is used.
Progress and next delivery times persist in the configured database. Blocked recipients are disabled for the current rotation.
Repeated Send Broadcast restarts the rotation at image one. Large audiences and Telegram rate limits can delay deliveries.

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
Drafts are temporary and are discarded on restart; saved users and the two-hour rotation are unaffected.

## Account access announcement (16 October 2026)

The next deployment queues the Turkish account-access announcement once for all saved private chats,
including the 23 additional IDs recovered from successful/failed delivery logs in the last seven days
(95 recovered IDs total). Logs are not a complete registry; preserve the live database before deploying.
The announcement is also the fourth message of the two-hour rotation: three withdrawal images then the text notice, repeating. Its delivery ledger persists
in `account_deliveries`: completed and blocked users are not requeued on restart; temporary failures retry.
As with Telegram sends generally, an interruption after Telegram accepts a message but before the ledger
commit can cause a duplicate on retry. Losing an ephemeral database also loses the delivery ledger.
New users in REDIRECT mode receive the same message in the /start registration caption. Normal-mode
/start behavior is unchanged. The account button and all registration/rotation links use https://strz.ac/CoxW.
Already-delivered Telegram messages are not edited. The live database migration to Neon remains pending.
