import os
import logging
import asyncio
import html
import hashlib
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

from utils.parser import extract_text_from_url
from utils.summarizer import summarize_text

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PROXY_URL = os.getenv("BOT_PROXY")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле!")

logging.basicConfig(level=logging.INFO)

# ---------- База данных ----------
DB_NAME = "cache.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cache
                 (url_hash TEXT PRIMARY KEY, summary TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  url TEXT,
                  timestamp DATETIME)''')
    conn.commit()
    conn.close()

def get_cached_summary(url: str) -> str | None:
    url_hash = hashlib.md5(url.encode()).hexdigest()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT summary FROM cache WHERE url_hash = ?", (url_hash,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def save_cached_summary(url: str, summary: str):
    url_hash = hashlib.md5(url.encode()).hexdigest()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO cache (url_hash, summary) VALUES (?, ?)",
              (url_hash, summary))
    conn.commit()
    conn.close()

def add_to_history(user_id: int, url: str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO user_history (user_id, url, timestamp) VALUES (?, ?, ?)",
              (user_id, url, datetime.now()))
    conn.commit()
    conn.close()

def get_user_history(user_id: int, limit: int = 5):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT url FROM user_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def clear_user_history_and_cache(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT url FROM user_history WHERE user_id = ?", (user_id,))
    urls = [row[0] for row in c.fetchall()]
    c.execute("DELETE FROM user_history WHERE user_id = ?", (user_id,))
    for url in urls:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        c.execute("DELETE FROM cache WHERE url_hash = ?", (url_hash,))
    conn.commit()
    conn.close()

init_db()
# ---------------------------------

# Настройки режимов суммаризации (max_length, min_length)
mode_params = {
    'short': {'max_length': 100, 'min_length': 40, 'name': 'Кратко'},
    'medium': {'max_length': 200, 'min_length': 80, 'name': 'Средне'},
    'long': {'max_length': 300, 'min_length': 120, 'name': 'Подробно'}
}
user_mode = {}

# Создаём бота с прокси
if PROXY_URL:
    bot = Bot(
        token=BOT_TOKEN,
        proxy=PROXY_URL,
        timeout=60,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    logging.info(f"✅ Бот запущен с прокси: {PROXY_URL}")
else:
    bot = Bot(token=BOT_TOKEN, timeout=60, default=DefaultBotProperties(parse_mode="HTML"))
    logging.info("⚠️ Бот запущен БЕЗ прокси. В РФ это может не работать.")

dp = Dispatcher()

# ---------- Постоянная reply-клавиатура ----------
def main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📚 О боте"), types.KeyboardButton(text="📊 Статистика")],
            [types.KeyboardButton(text="📜 Последние ссылки"), types.KeyboardButton(text="🗑 Очистить историю")],
            [types.KeyboardButton(text="📏 Длина пересказа")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

# ---------- Команды ----------
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот для суммаризации статей на русском языке.\n"
        "Просто отправь мне ссылку на статью, и я пришлю её краткое содержание.\n\n"
        "⚙️ При первом запуске может потребоваться 1-2 минуты на загрузку модели.",
        reply_markup=main_keyboard()
    )

@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "Доступные команды:\n"
        "/start – показать приветствие и меню\n"
        "/help – эта справка\n"
        "А также используйте кнопки внизу экрана для быстрого доступа к функциям.",
        reply_markup=main_keyboard()
    )

# ---------- Обработка reply-кнопок ----------
@dp.message(lambda msg: msg.text == "📚 О боте")
async def about_button(message: types.Message):
    await message.answer(
        "📚 <b>О боте</b>\n\n"
        "Я использую локальную модель rut5-base-absum, обученную специально "
        "для суммаризации русскоязычных текстов.\n"
        "Версия: 1.4\n"
        "Вы можете выбрать длину пересказа: кратко, средне, подробно.\n" \
        "Бот сделан Никитой Морфием"
    )

@dp.message(lambda msg: msg.text == "📊 Статистика")
async def stats_button(message: types.Message):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM cache")
    cache_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM user_history")
    history_count = c.fetchone()[0]
    conn.close()
    await message.answer(
        f"📊 <b>Статистика:</b>\n\n"
        f"Всего суммаризаций в кэше: {cache_count}\n"
        f"Всего запросов пользователей: {history_count}"
    )

@dp.message(lambda msg: msg.text == "📜 Последние ссылки")
async def history_button(message: types.Message):
    user_id = message.from_user.id
    urls = get_user_history(user_id, limit=5)
    if not urls:
        await message.answer("📭 У вас пока нет истории.")
        return
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    for i, url in enumerate(urls, 1):
        short_url = url[:50] + "..." if len(url) > 50 else url
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(text=f"{i}. {short_url}", callback_data=f"history_{url}")
        ])
    await message.answer(
        "📜 <b>Ваши последние ссылки:</b>\n\nНажмите на ссылку, чтобы увидеть суммаризацию.",
        reply_markup=keyboard
    )

@dp.message(lambda msg: msg.text == "🗑 Очистить историю")
async def clear_history_button(message: types.Message):
    user_id = message.from_user.id
    clear_user_history_and_cache(user_id)
    await message.answer("✅ История и связанный кэш очищены.")

@dp.message(lambda msg: msg.text == "📏 Длина пересказа")
async def length_menu(message: types.Message):
    user_id = message.from_user.id
    current = user_mode.get(user_id, 'medium')
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="📄 Кратко", callback_data="set_short"),
            types.InlineKeyboardButton(text="📑 Средне", callback_data="set_medium"),
            types.InlineKeyboardButton(text="📚 Подробно", callback_data="set_long")
        ]
    ])
    await message.answer(
        f"Текущий режим: <b>{current}</b>\nВыберите новую длину пересказа:",
        parse_mode="HTML",
        reply_markup=keyboard
    )

# ---------- Обработка инлайн-кнопок ----------
@dp.callback_query(lambda c: c.data in ("set_short", "set_medium", "set_long"))
async def set_length(callback: types.CallbackQuery):
    mode = callback.data[4:]  # убираем "set_"
    user_id = callback.from_user.id
    user_mode[user_id] = mode
    await callback.answer(f"✅ Установлен режим: {mode}")
    await callback.message.delete()

@dp.callback_query(lambda c: c.data.startswith("history_"))
async def show_summary_for_history(callback: types.CallbackQuery):
    url = callback.data[8:]  # убираем "history_"
    await callback.answer("⏳ Загружаю...")
    summary = get_cached_summary(url)
    if summary:
        escaped = html.escape(summary)
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="✏️ Изменить длину", callback_data=f"change_length_{url}")]
        ])
        await callback.message.answer(
            f"📝 <b>Краткое содержание:</b>\n\n{escaped}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return
    await callback.message.answer("⏳ Генерирую суммаризацию, это может занять время...")
    await handle_url(callback.message, url)

@dp.callback_query(lambda c: c.data.startswith("change_length_"))
async def change_length(callback: types.CallbackQuery):
    url = callback.data[14:]  # убираем "change_length_"
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="📄 Кратко", callback_data=f"regenerate_{url}_short"),
            types.InlineKeyboardButton(text="📑 Средне", callback_data=f"regenerate_{url}_medium"),
            types.InlineKeyboardButton(text="📚 Подробно", callback_data=f"regenerate_{url}_long")
        ]
    ])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Выберите желаемую длину пересказа:",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("regenerate_"))
async def regenerate_with_length(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    url = parts[1]
    mode = parts[2]  # short, medium, long
    await callback.answer(f"🔄 Генерирую {mode_params[mode]['name']} вариант...")
    # Удаляем старую суммаризацию из кэша, чтобы перегенерировать
    url_hash = hashlib.md5(url.encode()).hexdigest()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM cache WHERE url_hash = ?", (url_hash,))
    conn.commit()
    conn.close()
    # Передаём параметры режима (только max_length и min_length)
    params = mode_params[mode]
    await handle_url(callback.message, url, max_length=params['max_length'], min_length=params['min_length'])

# ---------- Основной обработчик ссылок ----------
async def handle_url(source_message: types.Message, url: str = None, max_length: int = 200, min_length: int = 80):
    if url is None:
        url = source_message.text.strip()
    if not url.startswith(('http://', 'https://')):
        await source_message.answer("❌ Пожалуйста, отправьте корректную ссылку, начинающуюся с http:// или https://")
        return

    user_id = source_message.from_user.id
    add_to_history(user_id, url)

    cached = get_cached_summary(url)
    if cached:
        escaped = html.escape(cached)
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="✏️ Изменить длину", callback_data=f"change_length_{url}")]
        ])
        await source_message.answer(
            f"📝 <b>Краткое содержание (из кэша):</b>\n\n{escaped}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    processing_msg = await source_message.answer("⏳ Обрабатываю ссылку, это может занять 20-30 секунд...")

    try:
        text = await extract_text_from_url(url)
        if not text:
            await processing_msg.edit_text("❌ Не удалось извлечь текст из этой ссылки. Проверьте, доступна ли страница.")
            return
        if len(text) < 100:
            await processing_msg.edit_text("❌ Текст слишком короткий для суммаризации.")
            return

        summary = await summarize_text(text, max_length=max_length, min_length=min_length)
        save_cached_summary(url, summary)

        escaped = html.escape(summary)
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="✏️ Изменить длину", callback_data=f"change_length_{url}")]
        ])
        await processing_msg.edit_text(
            f"📝 <b>Краткое содержание:</b>\n\n{escaped}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        logging.exception("Ошибка при обработке")
        await processing_msg.edit_text(f"⚠️ Произошла непредвиденная ошибка: {e}")

# ---------- Обработчик обычных сообщений ----------
@dp.message()
async def handle_text_message(message: types.Message):
    if message.text and not message.text.startswith(('📚', '📊', '📜', '🗑', '📏')):
        user_id = message.from_user.id
        if user_id not in user_mode:
            user_mode[user_id] = 'medium'
        mode = user_mode.get(user_id, 'medium')
        params = mode_params[mode]
        # Передаём только нужные параметры, без 'name'
        await handle_url(message, message.text, max_length=params['max_length'], min_length=params['min_length'])

# ---------- Запуск ----------
async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")