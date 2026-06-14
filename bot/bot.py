"""
Telegram <-> NVIDIA NIM bridge for Llama Nemotron Super 49B.

- Talks to Telegram via long-polling (outbound only; no inbound ports).
- Talks to NIM via its OpenAI-compatible API.
- Persists per-chat conversation history in SQLite so it survives restarts.
- Strips Nemotron's <think> reasoning traces before replying.
"""

import asyncio
import logging
import os
import re
import sqlite3
import time

from openai import AsyncOpenAI
from telegram import Update, constants
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --------------------------------------------------------------------------- #
# Config (from environment / docker-compose)
# --------------------------------------------------------------------------- #
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://nim:8000/v1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "not-needed")
MODEL_NAME = os.environ.get("MODEL_NAME", "nvidia/llama-3.3-nemotron-super-49b-v1.5")
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "You are a helpful, concise assistant.")
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "12"))
DB_PATH = os.environ.get("DB_PATH", "/data/conversations.db")
TELEGRAM_MAX_LEN = 4096

# Optional allowlist: comma-separated numeric Telegram user IDs. Empty = open.
_allowed = os.environ.get("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = {int(x) for x in _allowed.split(",") if x.strip()} if _allowed else set()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s", level=logging.INFO
)
log = logging.getLogger("nemotron-bot")

client = AsyncOpenAI(base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY)

# Nemotron toggles reasoning via a system directive.
THINK_DIRECTIVE = {True: "detailed thinking on", False: "detailed thinking off"}
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# --------------------------------------------------------------------------- #
# SQLite persistence (run via asyncio.to_thread to avoid blocking the loop)
# --------------------------------------------------------------------------- #
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                   chat_id INTEGER NOT NULL,
                   role    TEXT    NOT NULL,
                   content TEXT    NOT NULL,
                   ts      REAL    NOT NULL
               )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, ts)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                   chat_id   INTEGER PRIMARY KEY,
                   reasoning INTEGER NOT NULL DEFAULT 0
               )"""
        )


def _save_message(chat_id: int, role: str, content: str):
    with _db() as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, role, content, ts) VALUES (?,?,?,?)",
            (chat_id, role, content, time.time()),
        )


def _load_history(chat_id: int) -> list[dict]:
    # Last MAX_HISTORY_TURNS user+assistant pairs, oldest first.
    limit = MAX_HISTORY_TURNS * 2
    with _db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE chat_id=? ORDER BY ts DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


def _clear_history(chat_id: int):
    with _db() as conn:
        conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))


def _get_reasoning(chat_id: int) -> bool:
    with _db() as conn:
        row = conn.execute(
            "SELECT reasoning FROM settings WHERE chat_id=?", (chat_id,)
        ).fetchone()
    return bool(row[0]) if row else False


def _set_reasoning(chat_id: int, on: bool):
    with _db() as conn:
        conn.execute(
            "INSERT INTO settings (chat_id, reasoning) VALUES (?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET reasoning=excluded.reasoning",
            (chat_id, int(on)),
        )


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def _authorized(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    user = update.effective_user
    return bool(user and user.id in ALLOWED_USER_IDS)


# --------------------------------------------------------------------------- #
# Telegram handlers
# --------------------------------------------------------------------------- #
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I'm a local Nemotron Super 49B running on your DGX Spark.\n\n"
        "Just send a message to chat.\n\n"
        "Commands:\n"
        "/reset — clear this conversation's memory\n"
        "/think — toggle the model's reasoning mode\n"
        "/help — show this help"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await asyncio.to_thread(_clear_history, update.effective_chat.id)
    await update.message.reply_text("🧹 Conversation memory cleared.")


async def cmd_think(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    new = not await asyncio.to_thread(_get_reasoning, chat_id)
    await asyncio.to_thread(_set_reasoning, chat_id, new)
    await update.message.reply_text(
        f"🧠 Reasoning mode {'ON' if new else 'OFF'}. "
        + ("Replies may be slower but more thorough." if new else "Faster, direct replies.")
    )


async def _reply_chunked(update: Update, text: str):
    """Telegram caps messages at 4096 chars; split on boundaries."""
    text = text.strip() or "(empty response)"
    for i in range(0, len(text), TELEGRAM_MAX_LEN):
        await update.message.reply_text(text[i : i + TELEGRAM_MAX_LEN])


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await update.message.reply_text("⛔ Not authorized.")
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text
    reasoning = await asyncio.to_thread(_get_reasoning, chat_id)

    # Build the request: system directive + persisted history + new turn.
    history = await asyncio.to_thread(_load_history, chat_id)
    system = f"{THINK_DIRECTIVE[reasoning]}\n\n{SYSTEM_PROMPT}"
    messages = [{"role": "system", "content": system}]
    messages += history
    messages.append({"role": "user", "content": user_text})

    # Keep the "typing…" indicator alive while the model generates.
    async def keep_typing():
        try:
            while True:
                await ctx.bot.send_chat_action(chat_id, constants.ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    typing = asyncio.create_task(keep_typing())
    try:
        resp = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.6,
            max_tokens=2048,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:  # noqa: BLE001 — surface any backend error to the user
        log.exception("Inference error")
        typing.cancel()
        await update.message.reply_text(f"⚠️ Error talking to the model: {e}")
        return
    finally:
        typing.cancel()

    # Strip reasoning traces before showing/saving the visible answer.
    answer = _THINK_RE.sub("", raw).strip()

    # Persist the turn (store the cleaned answer, not the raw think-block).
    await asyncio.to_thread(_save_message, chat_id, "user", user_text)
    await asyncio.to_thread(_save_message, chat_id, "assistant", answer)

    await _reply_chunked(update, answer)


def main():
    init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("think", cmd_think))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("Starting bot. Model=%s base_url=%s", MODEL_NAME, OPENAI_BASE_URL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
