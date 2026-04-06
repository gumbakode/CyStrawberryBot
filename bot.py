import json
import logging
import os
import time as _time
from datetime import datetime, time
from pathlib import Path

import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

# --- Config ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
ACTIVE_HOURS_START = int(os.getenv("ACTIVE_HOURS_START", "5"))
ACTIVE_HOURS_END = int(os.getenv("ACTIVE_HOURS_END", "21"))
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "60"))

API_URL = "https://api.pittalisstrawberries.com/api/venting-machine"
API_BEARER = os.getenv("API_BEARER", "")

DATA_DIR = Path(os.getenv("DATA_DIR", "."))
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"
STATE_FILE = DATA_DIR / "state.json"
KIOSK_NAMES_FILE = Path(__file__).parent / "kiosk_names.json"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --- Storage helpers ---

def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


KIOSK_NAMES: dict[str, str] = load_json(KIOSK_NAMES_FILE, {})


# --- API ---

_kiosk_cache: dict = {"data": None, "ts": 0.0}


def fetch_kiosks(force: bool = False) -> list[dict]:
    now = _time.monotonic()
    if not force and _kiosk_cache["data"] is not None and now - _kiosk_cache["ts"] < CACHE_TTL:
        return _kiosk_cache["data"]

    resp = requests.get(
        API_URL,
        headers={
            "Authorization": f"Bearer {API_BEARER}",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    hidden = {"", "Unknown Device", "H"}
    result = []
    for k in resp.json()["api_response"]:
        if k["deviceName"].strip() in hidden:
            continue
        code = str(k["deviceCode"])
        if code in KIOSK_NAMES:
            k["deviceName"] = KIOSK_NAMES[code]
        result.append(k)
    _kiosk_cache["data"] = result
    _kiosk_cache["ts"] = now
    return result


def get_kiosks_from_state() -> list[dict]:
    """Get kiosk list from state.json (updated by background polling).
    Falls back to fetch_kiosks() if state.json is empty (first run)."""
    state = load_json(STATE_FILE, {})
    if not state:
        return fetch_kiosks()
    return [
        {
            "deviceCode": code,
            "deviceName": info["name"],
            "total_stock": info["stock"],
            "isOnline": info["online"],
        }
        for code, info in state.items()
    ]


# --- Time check ---

def is_active_time() -> bool:
    now = datetime.now().time()
    return time(ACTIVE_HOURS_START, 0) <= now < time(ACTIVE_HOURS_END, 0)


# --- Shared UI helpers ---

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Check stock", callback_data="status")],
        [
            InlineKeyboardButton("🔔 Subscribe", callback_data="sub_menu"),
            InlineKeyboardButton("🔕 Unsubscribe", callback_data="unsub_menu"),
        ],
    ])


def build_status_text(kiosks: list[dict]) -> str:
    lines = ["🍓 *Current strawberry stock:*\n"]
    for k in sorted(kiosks, key=lambda x: x["deviceName"]):
        name = k["deviceName"].strip()
        stock = k["total_stock"]
        icon = "🟢" if k["isOnline"] else "🔴"
        filled = round(stock / 40 * 5)
        bar = "🟩" * filled + "⬜" * (5 - filled)
        lines.append(f"{icon} *{name}*\n{stock}/40  {bar}")
    return "\n\n".join(lines)


def get_subs() -> dict[str, list[str]]:
    """Load subscribers. Format: {"chat_id": ["all"] | ["code1", "code2", ...]}"""
    data = load_json(SUBSCRIBERS_FILE, {})
    # migrate from old list format
    if isinstance(data, list):
        data = {cid: ["all"] for cid in data}
        save_json(SUBSCRIBERS_FILE, data)
    return data


def build_subscribe_keyboard(kiosks: list[dict], chat_id: str) -> InlineKeyboardMarkup:
    subs = get_subs()
    user_kiosks = subs.get(chat_id, [])
    rows = []
    is_all = "all" in user_kiosks
    check_all = "✅ " if is_all else ""
    rows.append([InlineKeyboardButton(f"{check_all}📋 All kiosks", callback_data="sub:all")])
    for k in sorted(kiosks, key=lambda x: x["deviceName"]):
        code = str(k["deviceCode"])
        name = k["deviceName"].strip()
        check = "✅ " if (is_all or code in user_kiosks) else ""
        rows.append([InlineKeyboardButton(f"{check}{name}", callback_data=f"sub:{code}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def build_unsubscribe_keyboard(kiosks: list[dict], chat_id: str) -> InlineKeyboardMarkup:
    subs = get_subs()
    user_kiosks = subs.get(chat_id, [])
    if not user_kiosks:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
        ])
    rows = []
    is_all = "all" in user_kiosks
    if is_all:
        rows.append([InlineKeyboardButton("❌ Unsubscribe from all", callback_data="unsub:all")])
    for k in sorted(kiosks, key=lambda x: x["deviceName"]):
        code = str(k["deviceCode"])
        name = k["deviceName"].strip()
        if is_all or code in user_kiosks:
            rows.append([InlineKeyboardButton(f"❌ {name}", callback_data=f"unsub:{code}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


# --- Command handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🍓 *Pittalis Strawberries Bot*\n\n"
        "I monitor strawberry stock in kiosks and notify you when they get restocked.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Fetching stock data...")
    try:
        kiosks = fetch_kiosks()
        await msg.edit_text(build_status_text(kiosks), parse_mode="Markdown")
    except Exception as e:
        logger.error("Error fetching kiosks for /status: %s", e)
        await msg.edit_text("⚠️ Failed to fetch data. Try again later.")


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    kiosks = get_kiosks_from_state()
    await update.message.reply_text(
        "Select kiosks to subscribe to:",
        reply_markup=build_subscribe_keyboard(kiosks, chat_id),
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subs = get_subs()
    if chat_id not in subs or not subs[chat_id]:
        await update.message.reply_text("You are not subscribed to any kiosks.")
        return
    kiosks = get_kiosks_from_state()
    await update.message.reply_text(
        "Select kiosks to unsubscribe from:",
        reply_markup=build_unsubscribe_keyboard(kiosks, chat_id),
    )


# --- Inline button handler ---

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = str(query.from_user.id)

    if query.data == "status":
        await query.answer()
        msg = await query.message.reply_text("⏳ Fetching stock data...")
        try:
            kiosks = fetch_kiosks()
            await msg.edit_text(build_status_text(kiosks), parse_mode="Markdown")
        except Exception as e:
            logger.error("Error fetching kiosks for button status: %s", e)
            await msg.edit_text("⚠️ Failed to fetch data. Try again later.")

    elif query.data == "back_main":
        await query.answer()
        await query.edit_message_text(
            "🍓 *Pittalis Strawberries Bot*\n\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )

    elif query.data == "sub_menu":
        await query.answer()
        kiosks = get_kiosks_from_state()
        await query.edit_message_text(
            "Select kiosks to subscribe to:",
            reply_markup=build_subscribe_keyboard(kiosks, chat_id),
        )

    elif query.data == "unsub_menu":
        await query.answer()
        subs = get_subs()
        if chat_id not in subs or not subs[chat_id]:
            await query.answer("You are not subscribed to any kiosks.", show_alert=True)
            return
        kiosks = get_kiosks_from_state()
        await query.edit_message_text(
            "Select kiosks to unsubscribe from:",
            reply_markup=build_unsubscribe_keyboard(kiosks, chat_id),
        )

    elif query.data.startswith("sub:"):
        code = query.data[4:]
        subs = get_subs()
        user_kiosks = subs.get(chat_id, [])

        if code == "all":
            if "all" in user_kiosks:
                await query.answer("Already subscribed to all.")
                return
            subs[chat_id] = ["all"]
        else:
            if "all" in user_kiosks:
                await query.answer("Already subscribed to all kiosks.")
                return
            if code in user_kiosks:
                await query.answer("Already subscribed to this kiosk.")
                return
            user_kiosks.append(code)
            subs[chat_id] = user_kiosks

        save_json(SUBSCRIBERS_FILE, subs)
        await query.answer("✅ Subscribed!")
        kiosks = get_kiosks_from_state()
        await query.edit_message_reply_markup(
            reply_markup=build_subscribe_keyboard(kiosks, chat_id),
        )

    elif query.data.startswith("unsub:"):
        code = query.data[6:]
        subs = get_subs()
        user_kiosks = subs.get(chat_id, [])

        if code == "all":
            subs.pop(chat_id, None)
            save_json(SUBSCRIBERS_FILE, subs)
            await query.answer("❌ Unsubscribed from all.")
            await query.edit_message_text(
                "🍓 *Pittalis Strawberries Bot*\n\nChoose an option:",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
            return
        else:
            if "all" in user_kiosks:
                # switching from "all" to specific: subscribe to everything except this one
                kiosks = get_kiosks_from_state()
                all_codes = [str(k["deviceCode"]) for k in kiosks]
                user_kiosks = [c for c in all_codes if c != code]
            else:
                if code in user_kiosks:
                    user_kiosks.remove(code)

            if user_kiosks:
                subs[chat_id] = user_kiosks
            else:
                subs.pop(chat_id, None)

        save_json(SUBSCRIBERS_FILE, subs)
        await query.answer("❌ Unsubscribed!")
        if chat_id in subs and subs[chat_id]:
            kiosks = get_kiosks_from_state()
            await query.edit_message_reply_markup(
                reply_markup=build_unsubscribe_keyboard(kiosks, chat_id),
            )
        else:
            await query.edit_message_text(
                "🍓 *Pittalis Strawberries Bot*\n\nChoose an option:",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )


# --- Unknown message handler ---

async def on_unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Use the menu below 👇",
        reply_markup=main_menu_keyboard(),
    )


# --- Background polling job ---

async def poll_and_notify(context: ContextTypes.DEFAULT_TYPE):
    if not is_active_time():
        return

    subs = get_subs()
    if not subs:
        return

    try:
        kiosks = fetch_kiosks(force=True)
    except Exception as e:
        logger.error("Error fetching kiosks in background job: %s", e)
        return

    state: dict = load_json(STATE_FILE, {})
    # collect notifications per kiosk code
    kiosk_notifications: dict[str, str] = {}

    for k in kiosks:
        code = str(k["deviceCode"])
        name = k["deviceName"].strip()
        stock = int(k["total_stock"])
        online = bool(k["isOnline"])
        prev = state.get(code, {})
        prev_stock = prev.get("stock")
        prev_online = prev.get("online")

        msgs = []
        if prev_stock is not None and stock > prev_stock:
            if prev_stock == 0:
                msgs.append(
                    f"🍓 *Restocked!* {name}\n"
                    f"Was: 0 → Now: *{stock}/40*"
                )
            else:
                msgs.append(
                    f"📈 *Stock increased!* {name}\n"
                    f"Was: {prev_stock} → Now: *{stock}/40*"
                )

        if prev_online is not None and online != prev_online:
            if online:
                msgs.append(f"🟢 *{name}* is back online")
            else:
                msgs.append(f"🔴 *{name}* went offline")

        if msgs:
            kiosk_notifications[code] = "\n\n".join(msgs)

        state[code] = {"stock": stock, "online": online, "name": name}

    save_json(STATE_FILE, state)

    if not kiosk_notifications:
        return

    for chat_id, user_kiosks in subs.items():
        is_all = "all" in user_kiosks
        relevant = [
            msg for code, msg in kiosk_notifications.items()
            if is_all or code in user_kiosks
        ]
        if not relevant:
            continue
        text = "\n\n".join(relevant)
        try:
            await context.bot.send_message(
                chat_id=int(chat_id),
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Failed to send notification to %s: %s", chat_id, e)


# --- Entry point ---

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env file")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_unknown_message))

    app.job_queue.run_repeating(poll_and_notify, interval=POLL_INTERVAL, first=5)

    logger.info(
        "Bot started. Polling every %ds, active hours %d:00–%d:00",
        POLL_INTERVAL,
        ACTIVE_HOURS_START,
        ACTIVE_HOURS_END,
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
