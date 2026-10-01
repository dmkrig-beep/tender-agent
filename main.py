import asyncio
import html
import logging
import os
import sqlite3
from datetime import datetime

import feedparser
from telegram import Bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tender-agent")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RSS_URLS = [u.strip() for u in os.getenv("RSS_URLS", "").split(",") if u.strip()]
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "600"))
DB_PATH = os.getenv("DB_PATH", "/data/tenders.db")
KEYWORDS = [k.strip().lower() for k in os.getenv("KEYWORDS", "").split(",") if k.strip()]

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS seen_tenders (
        guid TEXT PRIMARY KEY, title TEXT, link TEXT, published TEXT, created_at TEXT)""")
    conn.commit()
    return conn

def is_new(conn, guid):
    return conn.execute("SELECT 1 FROM seen_tenders WHERE guid = ?", (guid,)).fetchone() is None

def mark_seen(conn, guid, title, link, published):
    conn.execute("INSERT OR IGNORE INTO seen_tenders VALUES (?, ?, ?, ?, ?)",
                 (guid, title, link, published, datetime.utcnow().isoformat()))
    conn.commit()

def matches_keywords(title):
    if not KEYWORDS:
        return True
    return any(k in title.lower() for k in KEYWORDS)

async def send_telegram(bot, text):
    await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML", disable_web_page_preview=True)

async def check_feed(bot, conn, url):
    logger.info("Проверка RSS: %s", url)
    feed = await asyncio.to_thread(feedparser.parse, url)
    for entry in feed.entries:
        guid = entry.get("id") or entry.get("guid") or entry.get("link")
        title = entry.get("title", "Без названия")
        link = entry.get("link", "")
        published = entry.get("published", "")
        if not guid or not is_new(conn, guid):
            continue
        if not matches_keywords(title):
            mark_seen(conn, guid, title, link, published)
            continue
        message = (f"🆕 <b>Новый тендер</b>\n\n<b>Название:</b> {html.escape(title)}\n"
                   f"<b>Опубликовано:</b> {html.escape(published)}\n"
                   f"<a href=\"{html.escape(link, quote=True)}\">Открыть закупку</a>")
        try:
            await send_telegram(bot, message)
            mark_seen(conn, guid, title, link, published)
            logger.info("Отправлен: %s", title[:80])
        except Exception:
            logger.exception("Ошибка отправки")

async def main():
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("Не заданы TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID")
        return
    bot = Bot(token=BOT_TOKEN)
    conn = init_db()
    while True:
        try:
            for url in RSS_URLS:
                await check_feed(bot, conn, url)
        except Exception:
            logger.exception("Ошибка в цикле")
        await asyncio.sleep(CHECK_INTERVAL)
if __name__ == "__main__":
    asyncio.run(main())
