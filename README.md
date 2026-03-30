# StrawberryBot

Telegram bot that monitors [Pittalis Strawberries](https://pittalisstrawberries.com/) vending machine kiosks and sends notifications when stock changes.

## Features

- **Check stock** — see current strawberry levels across all kiosks with visual progress bars
- **Per-kiosk subscriptions** — subscribe to specific kiosks or all at once
- **Restock alerts** — get notified when a kiosk is restocked or stock increases
- **Online/offline alerts** — get notified when a kiosk goes online or offline
- **Active hours** — notifications are only sent during configurable hours (default 5:00–21:00)

## Setup

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather)
2. Copy `.env.example` to `.env` and fill in the values:
   ```
   cp .env.example .env
   ```

### Docker (recommended)

```bash
mkdir data
docker compose up -d
```

### Manual

```bash
./start.sh
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Bot token from BotFather (required) |
| `API_BEARER` | — | Pittalis API bearer token (required) |
| `POLL_INTERVAL_SECONDS` | `60` | How often to check for stock changes |
| `ACTIVE_HOURS_START` | `5` | Hour to start sending notifications |
| `ACTIVE_HOURS_END` | `21` | Hour to stop sending notifications |

## Bot commands

| Command | Description |
|---|---|
| `/start` | Open main menu with inline buttons |
| `/status` | Check current stock levels |
| `/subscribe` | Choose kiosks to get notifications for |
| `/unsubscribe` | Remove kiosk subscriptions |
