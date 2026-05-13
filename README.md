# Today Bot

Telegram bot for a personal daily briefing. It combines Todoist tasks and iCal calendars, then sends a morning digest and on-demand summaries in chat.

## Features

- Shows Todoist tasks for today and overdue tasks
- Shows events from one or more iCal calendars
- Sends a scheduled morning digest
- Sends a daily 20:00 reminder to clean Todoist Inbox
- Adds weather to the morning digest (temperature, precipitation chance, UV, air quality)
- Saves forwarded messages to Todoist Inbox automatically
- Exposes recent bot logs with `/logs` for quick diagnostics
- Supports admin-only controls inside Telegram
- Lets you configure timezone and calendar sources from the bot UI
- Prevents duplicate bot instances with a local lock file

## Stack

- Python
- `python-telegram-bot`
- Todoist API v1
- Open-Meteo API
- iCal parsing with `icalendar` and `recurring-ical-events`
- Local JSON settings storage

## Project Structure

```text
.
├── app/
│   ├── bot.py
│   ├── main.py
│   ├── stop.py
│   └── services/
│       ├── ical.py
│       ├── settings.py
│       ├── todoist.py
│       └── weather.py
├── requirements.txt
└── .env
```

## Requirements

- Python 3.11+
- Telegram bot token
- Todoist API token
- Telegram numeric user id for the bot admin

## Environment Variables

Create a local `.env` file in the project root:

```env
TELEGRAM_BOT_TOKEN=
TODOIST_API_TOKEN=
ADMIN_USER_ID=
```

These values are local-only and should not be committed. The repository ignores `.env` by default.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

Start the bot from the repository root:

```bash
python3 -m app.main
```

Stop the running bot cleanly:

```bash
python3 -m app.stop
```

## Run with Docker

The project includes a multi-arch Docker setup that works on Raspberry Pi and can be used in CasaOS.

### Files

- `Dockerfile` builds the bot image
- `docker-compose.yml` runs the container with environment variables and persistent data
- `.dockerignore` keeps local secrets and runtime files out of the image build context

### Start locally with Docker

Make sure `.env` exists in the project root, then run:

```bash
docker compose up -d --build
```

Stop the container:

```bash
docker compose down
```

### CasaOS on Raspberry Pi

In CasaOS, create a custom app or compose stack from this repository and use the included `docker-compose.yml`.

Important notes:

- set these three environment variables in the CasaOS UI:
  - `TELEGRAM_BOT_TOKEN`
  - `TODOIST_API_TOKEN`
  - `ADMIN_USER_ID`
- you do not need to mount or copy a `.env` file in CasaOS if you set variables in the UI
- the container runs `python -m app.main` automatically
- the compose file uses a persistent Docker volume for app data

### Docker Data Persistence

The container stores runtime files in:

- `/app/app/data/settings.json`
- `/app/app/data/bot.lock`

These are stored in the persistent Docker volume `today-bot-data`.

If you prefer a host bind mount in CasaOS, replace:

```yaml
volumes:
  - today-bot-data:/app/app/data
```

with something like:

```yaml
volumes:
  - /DATA/AppData/today-bot/data:/app/app/data
```

## Telegram Commands

- `/start` - show the main menu
- `/tasks` - show Todoist tasks for today and overdue tasks
- `/events` - show today's calendar events
- `/admin` - open admin controls
- `/morning_test` - send the morning digest immediately
- `/inbox_reminder_test` - send inbox reminder immediately
- `/weekly_inbox_test` - compatibility alias for inbox reminder test
- `/logs` - show recent bot log lines (admin only)

Forwarded messages sent to the bot in a private chat are automatically saved to Todoist Inbox:

- task title: `Forwarded from: <source>`
- task description: full message text/caption

Daily inbox reminder behavior:

- if Inbox task count is greater than `0`, bot sends a cleanup reminder with task count
- if Inbox task count is `0`, bot sends a motivational message instead

## Admin Controls

The admin panel in Telegram supports:

- timezone updates
- adding calendar ICS URLs
- weather location setup (auto by server IP or manual coordinates)
- removing configured calendars
- sending a test morning digest
- sending a test inbox reminder

Only the user whose Telegram id matches `ADMIN_USER_ID` can use these actions.

## Local Data

Runtime data is stored under `app/data/`.

- `app/data/settings.json` stores timezone and calendar URLs
- `app/data/bot.lock` is used to prevent multiple running instances
- `app/data/bot.log` stores rotating runtime logs used by `/logs`

The entire `app/data/` directory is ignored by git.

## Notes

- Todoist requests use `https://api.todoist.com/api/v1`
- weather uses Open-Meteo forecast + air quality endpoints
- rain warning is highlighted when precipitation probability is `>=30%`
- UV warning is highlighted when UV index is `>=5`
- Calendar sources support both `https://` and `webcal://` URLs
- If the bot says another instance is running, use `python3 -m app.stop` or remove a stale lock by starting the bot again after the old process is gone
