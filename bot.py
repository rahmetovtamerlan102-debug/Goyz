import logging
import time
import asyncio
import requests
import random
import string
import os
import asyncpg
import hmac
import hashlib
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, PreCheckoutQuery, SuccessfulPayment
from aiogram.enums import ParseMode
from aiogram import F
from aiohttp import web

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан! Добавьте переменную окружения BOT_TOKEN")

# Настройки Platega
PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET")
PLATEGA_API_URL = "https://app.platega.io/"

BOT_NAME = "Hunter"
SUPPORT_USERNAME = "crytcore"
PORT = int(os.getenv("PORT", 8080))
REQUIRED_CHANNEL = "@huntergoaj"
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL не задан! Добавьте переменную окружения DATABASE_URL")

if not PLATEGA_MERCHANT_ID or not PLATEGA_SECRET:
    logging.warning("PLATEGA_MERCHANT_ID или PLATEGA_SECRET не заданы! Платежи не будут работать")

# ========== ОПРЕДЕЛЕНИЕ WEBHOOK_URL ДЛЯ RENDER ==========

def get_webhook_url():
    """Автоматически определяет webhook_url для Platega (Render)"""
    
    # 1. Проверяем переменную окружения (приоритет)
    custom_url = os.getenv("PLATEGA_WEBHOOK_URL")
    if custom_url:
        return custom_url
    
    # 2. Для Render - используем RENDER_EXTERNAL_URL
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        return f"{render_url}/platega_webhook"
    
    # 3. Если ничего не нашли, используем дефолтный
    logging.warning("WEBHOOK_URL не определён для Render, используется дефолтный")
    return "https://your-domain.com/platega_webhook"

# ========== ИНИЦИАЛИЗАЦИЯ БОТА ==========
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ========== АДМИНЫ ==========
ADMIN_IDS = [8559629118]

# ========== ПРЯМЫЕ ССЫЛКИ НА КАРТИНКИ ==========
IMG_MENU = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21400"
IMG_SEARCH = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21404"
IMG_PREMIUM = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21408"
IMG_REFERRALS = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21402"
IMG_RESULT = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21406"
IMG_PROFILE = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21421"
IMG_MAGNET = "https://files.catbox.moe/fix4in.jpg"
IMG_FILTERS = "https://files.catbox.moe/0e8tgl.jpg"
IMG_SUPPORT = "https://files.catbox.moe/nu6cv6.png"
IMG_FALLBACK = "https://i.ibb.co/your-fallback-image.jpg"

# ========== СОСТОЯНИЯ ==========
admin_states = {}
waiting_for_words = set()

# ========== ОЧИСТКА СОСТОЯНИЯ ==========

def clear_waiting_state(user_id: int):
    waiting_for_words.discard(user_id)

# ========== ФУНКЦИИ БАЗЫ ДАННЫХ ==========

async def init_db():
    max_retries = 5
    retry_delay = 3
    
    for attempt in range(max_retries):
        try:
            logging.info(f"Попытка подключения к БД #{attempt + 1}")
            conn = await asyncpg.connect(DATABASE_URL, timeout=30)
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    attempts INTEGER DEFAULT 3,
                    max_attempts INTEGER DEFAULT 3,
                    invited INTEGER DEFAULT 0,
                    is_premium BOOLEAN DEFAULT FALSE,
                    premium_until TIMESTAMP,
                    username TEXT,
                    last_reset TIMESTAMP,
                    is_subscribed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    pending_length INTEGER DEFAULT 5
                )
            ''')
            
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS attempts INTEGER DEFAULT 3')
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS max_attempts INTEGER DEFAULT 3')
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS invited INTEGER DEFAULT 0')
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE')
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMP')
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS last_reset TIMESTAMP')
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_subscribed BOOLEAN DEFAULT FALSE')
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_length INTEGER DEFAULT 5')
            
            await conn.execute("""
                UPDATE users
                SET attempts = COALESCE(attempts, 3),
                    max_attempts = COALESCE(max_attempts, 3),
                    invited = COALESCE(invited, 0),
                    is_premium = COALESCE(is_premium, FALSE)
            """)
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    username TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS favorites_user_username_idx
                ON favorites(user_id, username)
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS filters (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    length INTEGER DEFAULT 6,
                    chars TEXT DEFAULT 'только буквы',
                    chars_type TEXT DEFAULT 'letters',
                    generation TEXT DEFAULT 'читаемые сочетания',
                    words TEXT[] DEFAULT '{}'
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id SERIAL PRIMARY KEY,
                    admin_id BIGINT,
                    action TEXT,
                    target_user BIGINT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS processed_payments (
                    payment_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.close()
            logging.info("База данных успешно инициализирована")
            return True
            
        except Exception as e:
            logging.error(f"Ошибка подключения к БД (попытка {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
            else:
                logging.critical("Не удалось подключиться к базе данных после всех попыток")
                raise
    
    return False

async def get_user(user_id: int):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        user = await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
        await conn.close()
        return user
    except Exception as e:
        logging.error(f"Ошибка get_user: {e}")
        return None

async def create_user(user_id: int, username: str = None):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            INSERT INTO users (user_id, username, attempts, max_attempts, last_reset)
            VALUES ($1, $2, 3, 3, NOW())
            ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
        ''', user_id, username)
        await conn.close()
    except Exception as e:
        logging.error(f"Ошибка create_user: {e}")

async def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        set_clause = ', '.join([f"{key} = ${i+2}" for i, key in enumerate(kwargs.keys())])
        values = [user_id] + list(kwargs.values())
        await conn.execute(f'UPDATE users SET {set_clause} WHERE user_id = $1', *values)
        await conn.close()
    except Exception as e:
        logging.error(f"Ошибка update_user: {e}")

async def reset_attempts_if_needed(user_id: int):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        user = await conn.fetchrow('SELECT attempts, max_attempts, last_reset FROM users WHERE user_id = $1', user_id)
        
        if not user:
            await conn.close()
            return False
        
        last_reset = user['last_reset']
        now = datetime.now()
        
        if last_reset is None or (now - last_reset).days >= 1:
            await conn.execute('''
                UPDATE users 
                SET attempts = max_attempts, last_reset = $1 
                WHERE user_id = $2
            ''', now, user_id)
            await conn.close()
            return True
        
        await conn.close()
        return False
    except Exception as e:
        logging.error(f"Ошибка reset_attempts_if_needed: {e}")
        return False

async def get_favorites(user_id: int):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        favorites = await conn.fetch('SELECT username FROM favorites WHERE user_id = $1', user_id)
        await conn.close()
        return [f['username'] for f in favorites]
    except Exception as e:
        logging.error(f"Ошибка get_favorites: {e}")
        return []

async def add_favorite(user_id: int, username: str):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            INSERT INTO favorites (user_id, username) VALUES ($1, $2)
            ON CONFLICT (user_id, username) DO NOTHING
        ''', user_id, username)
        await conn.close()
    except Exception as e:
        logging.error(f"Ошибка add_favorite: {e}")

async def clear_favorites(user_id: int):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('DELETE FROM favorites WHERE user_id = $1', user_id)
        await conn.close()
    except Exception as e:
        logging.error(f"Ошибка clear_favorites: {e}")

async def get_filters(user_id: int):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        filters = await conn.fetchrow('SELECT * FROM filters WHERE user_id = $1', user_id)
        await conn.close()
        
        if not filters:
            return {"length": 6, "chars": "только буквы", "chars_type": "letters", "generation": "читаемые сочетания", "words": []}
        
        return dict(filters)
    except Exception as e:
        logging.error(f"Ошибка get_filters: {e}")
        return {"length": 6, "chars": "только буквы", "chars_type": "letters", "generation": "читаемые сочетания", "words": []}

async def update_filters(user_id: int, **kwargs):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        existing = await conn.fetchrow('SELECT 1 FROM filters WHERE user_id = $1', user_id)
        
        if existing:
            set_clause = ', '.join([f"{key} = ${i+2}" for i, key in enumerate(kwargs.keys())])
            values = [user_id] + list(kwargs.values())
            await conn.execute(f'UPDATE filters SET {set_clause} WHERE user_id = $1', *values)
        else:
            columns = ['user_id'] + list(kwargs.keys())
            placeholders = ', '.join([f"${i+1}" for i in range(len(columns))])
            values = [user_id] + list(kwargs.values())
            await conn.execute(f'INSERT INTO filters ({", ".join(columns)}) VALUES ({placeholders})', *values)
        
        await conn.close()
    except Exception as e:
        logging.error(f"Ошибка update_filters: {e}")

async def log_admin_action(admin_id: int, action: str, target_user: int = None, details: str = None):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            INSERT INTO admin_logs (admin_id, action, target_user, details)
            VALUES ($1, $2, $3, $4)
        ''', admin_id, action, target_user, details)
        await conn.close()
    except Exception as e:
        logging.error(f"Ошибка log_admin_action: {e}")

async def get_all_users():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        users = await conn.fetch('SELECT * FROM users ORDER BY created_at DESC')
        await conn.close()
        return users
    except Exception as e:
        logging.error(f"Ошибка get_all_users: {e}")
        return []

async def get_stats():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        total = await conn.fetchval('SELECT COUNT(*) FROM users')
        premium = await conn.fetchval('SELECT COUNT(*) FROM users WHERE is_premium = TRUE')
        total_attempts = await conn.fetchval('SELECT SUM(attempts) FROM users')
        avg_attempts = await conn.fetchval('SELECT AVG(attempts) FROM users')
        
        yesterday = datetime.now() - timedelta(days=1)
        active = await conn.fetchval('SELECT COUNT(*) FROM users WHERE last_reset > $1', yesterday)
        
        await conn.close()
        return {
            "total": total or 0,
            "premium": premium or 0,
            "active": active or 0,
            "total_attempts": total_attempts or 0,
            "avg_attempts": round(avg_attempts or 0, 1)
        }
    except Exception as e:
        logging.error(f"Ошибка get_stats: {e}")
        return {"total": 0, "premium": 0, "active": 0, "total_attempts": 0, "avg_attempts": 0}

async def set_pending_length(user_id: int, length: int):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('UPDATE users SET pending_length = $1 WHERE user_id = $2', length, user_id)
        await conn.close()
    except Exception as e:
        logging.error(f"Ошибка set_pending_length: {e}")

async def get_pending_length(user_id: int):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        result = await conn.fetchval('SELECT pending_length FROM users WHERE user_id = $1', user_id)
        await conn.close()
        return result or 5
    except Exception as e:
        logging.error(f"Ошибка get_pending_length: {e}")
        return 5

# ========== ИДЕМПОТЕНТНОСТЬ ==========

async def mark_invoice_processed(payment_id: str) -> bool:
    if not payment_id:
        return True
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        result = await conn.execute('''
            INSERT INTO processed_payments (payment_id)
            VALUES ($1)
            ON CONFLICT (payment_id) DO NOTHING
        ''', payment_id)
        await conn.close()
        return result == "INSERT 0 1"
    except Exception as e:
        logging.error(f"Ошибка mark_invoice_processed: {e}")
        return True

# ========== АТОМАРНОЕ ПРОДЛЕНИЕ PREMIUM ==========

async def extend_premium(user_id: int, days: int) -> datetime:
    logging.info(f"Продление Premium для {user_id} на {days} дней")
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        result = await conn.fetchrow('''
            UPDATE users
            SET is_premium = TRUE,
                premium_until = GREATEST(COALESCE(premium_until, NOW()), NOW()) + ($1 * INTERVAL '1 day')
            WHERE user_id = $2
            RETURNING premium_until
        ''', days, user_id)
        await conn.close()
        
        if result:
            logging.info(f"Premium для {user_id} продлён до {result['premium_until']}")
        else:
            logging.warning(f"Пользователь {user_id} не найден при продлении Premium")
        
        return result['premium_until'] if result else None
    except Exception as e:
        logging.error(f"Ошибка extend_premium: {e}")
        return None

# ========== ПРОВЕРКА ПОДПИСКИ ==========

async def check_subscription(user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logging.warning(f"Не удалось проверить подписку: {e}")
        return True

# ========== БЕЗОПАСНАЯ ОТПРАВКА ==========

async def safe_answer_photo(message: types.Message, photo: str, caption: str, reply_markup=None, parse_mode=None):
    try:
        kwargs = {
            "photo": photo,
            "caption": caption,
            "reply_markup": reply_markup
        }
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        
        await message.answer_photo(**kwargs)
        return True
    except Exception as e:
        logging.warning(f"Не удалось отправить фото {photo}: {e}")
        try:
            await message.answer_photo(
                photo=IMG_FALLBACK,
                caption=caption,
                reply_markup=reply_markup
            )
            return True
        except:
            await message.answer(
                caption,
                reply_markup=reply_markup
            )
            return False

async def safe_edit_text(message: types.Message, text: str, reply_markup=None, parse_mode=None):
    try:
        kwargs = {
            "text": text,
            "reply_markup": reply_markup
        }
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        
        await message.edit_text(**kwargs)
        return True
    except Exception as e:
        logging.warning(f"Не удалось отредактировать текст: {e}")
        try:
            await message.delete()
        except:
            pass
        await message.answer(
            text=text,
            reply_markup=reply_markup
        )
        return False

# ========== КЛАВИАТУРЫ ==========

def main_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Поиск", callback_data="search"), 
         InlineKeyboardButton(text="Premium", callback_data="premium")],
        [InlineKeyboardButton(text="Мой профиль", callback_data="profile"), 
         InlineKeyboardButton(text="Рефералы", callback_data="referrals")],
        [InlineKeyboardButton(text="Поддержка", callback_data="support")]
    ])
    return keyboard

def back_to_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])

def search_options_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="5 символов", callback_data="search_5"),
         InlineKeyboardButton(text="6 символов", callback_data="search_6")],
        [InlineKeyboardButton(text="Фильтры", callback_data="search_filters"),
         InlineKeyboardButton(text="Магнит", callback_data="search_magnet")],
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
    return keyboard

def filters_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить длину", callback_data="filter_length")],
        [InlineKeyboardButton(text="Изменить символы", callback_data="filter_chars")],
        [InlineKeyboardButton(text="Изменить тип генерации", callback_data="filter_generation")],
        [InlineKeyboardButton(text="Добавить слова", callback_data="filter_words")],
        [InlineKeyboardButton(text="Начать поиск", callback_data="filter_start")],
        [InlineKeyboardButton(text="Сбросить настройки", callback_data="filter_reset")],
        [InlineKeyboardButton(text="Назад", callback_data="search")]
    ])
    return keyboard

def chars_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Только буквы", callback_data="chars_letters")],
        [InlineKeyboardButton(text="Буквы и цифры", callback_data="chars_letters_digits")],
        [InlineKeyboardButton(text="Назад", callback_data="search")]
    ])
    return keyboard

def magnet_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Обычный", callback_data="magnet_normal"),
         InlineKeyboardButton(text="Fast", callback_data="magnet_fast")],
        [InlineKeyboardButton(text="Mythoc", callback_data="magnet_mythoc")],
        [InlineKeyboardButton(text="Назад", callback_data="search")]
    ])
    return keyboard

def search_progress_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить поиск", callback_data="cancel_search")]
    ])
    return keyboard

def search_result_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В избранное", callback_data="favorite")],
        [InlineKeyboardButton(text="Найти ещё", callback_data="search")],
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
    return keyboard

def profile_menu(favorites_count=0):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Избранное ({favorites_count})", callback_data="favorites_list")],
        [InlineKeyboardButton(text="Информация", callback_data="info")],
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
    return keyboard

def favorites_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мой профиль", callback_data="profile_from_favorites")]
    ])
    return keyboard

def referrals_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])

def premium_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Что входит?", callback_data="premium_info")],
        [InlineKeyboardButton(text="Купить Premium", callback_data="buy_premium_choose")],
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
    return keyboard

def buy_premium_choose_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="USD (крипта)", callback_data="buy_premium_usd_choose")],
        [InlineKeyboardButton(text="СБП (рубли)", callback_data="buy_premium_rub_choose")],
        [InlineKeyboardButton(text="Назад", callback_data="premium")]
    ])
    return keyboard

def buy_premium_usd_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 день - 1 USD", callback_data="usd_1")],
        [InlineKeyboardButton(text="3 дня - 2 USD", callback_data="usd_3")],
        [InlineKeyboardButton(text="7 дней - 3 USD", callback_data="usd_7")],
        [InlineKeyboardButton(text="30 дней - 5 USD", callback_data="usd_30")],
        [InlineKeyboardButton(text="Назад", callback_data="buy_premium_choose")]
    ])
    return keyboard

def buy_premium_rub_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 день - 29 ₽", callback_data="rub_1")],
        [InlineKeyboardButton(text="3 дня - 50 ₽", callback_data="rub_3")],
        [InlineKeyboardButton(text="7 дней - 99 ₽", callback_data="rub_7")],
        [InlineKeyboardButton(text="30 дней - 149 ₽", callback_data="rub_30")],
        [InlineKeyboardButton(text="Назад", callback_data="buy_premium_choose")]
    ])
    return keyboard

def support_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Написать в поддержку", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
    return keyboard

def filter_length_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="4", callback_data="filter_len_4"),
         InlineKeyboardButton(text="5", callback_data="filter_len_5"),
         InlineKeyboardButton(text="6", callback_data="filter_len_6")],
        [InlineKeyboardButton(text="7", callback_data="filter_len_7"),
         InlineKeyboardButton(text="8", callback_data="filter_len_8"),
         InlineKeyboardButton(text="9", callback_data="filter_len_9")],
        [InlineKeyboardButton(text="Назад", callback_data="search_filters")]
    ])
    return keyboard

def subscription_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Проверить подписки", callback_data="check_subscription")]
    ])
    return keyboard

# ========== АДМИН-КЛАВИАТУРЫ ==========

def admin_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="Выдать Premium", callback_data="admin_give_premium")],
        [InlineKeyboardButton(text="Забрать Premium", callback_data="admin_remove_premium")],
        [InlineKeyboardButton(text="Выдать запросы", callback_data="admin_add_attempts")],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="Рефералы", callback_data="admin_refs")],
        [InlineKeyboardButton(text="Назад", callback_data="menu")]
    ])
    return keyboard

def admin_back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="admin_panel")]
    ])

def admin_cancel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="admin_cancel")]
    ])

def admin_premium_days_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 дней", callback_data="admin_premium_7")],
        [InlineKeyboardButton(text="14 дней", callback_data="admin_premium_14")],
        [InlineKeyboardButton(text="30 дней", callback_data="admin_premium_30")],
        [InlineKeyboardButton(text="60 дней", callback_data="admin_premium_60")],
        [InlineKeyboardButton(text="90 дней", callback_data="admin_premium_90")],
        [InlineKeyboardButton(text="Отмена", callback_data="admin_cancel")]
    ])
    return keyboard

# ========== ФУНКЦИИ ПРОВЕРКИ ==========

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def generate_username(length: int, chars_type: str = "letters") -> str:
    if chars_type == "letters":
        chars = string.ascii_lowercase
    else:
        chars = string.ascii_lowercase + string.digits
    
    return ''.join(random.choices(chars, k=length))

def check_username(username: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    result = {
        "username": username,
        "available": False,
        "telegram": False,
        "fragment": False
    }
    
    try:
        tg_resp = requests.get(f"https://t.me/{username}", headers=headers, timeout=10)
        if "If you have Telegram, you can contact" not in tg_resp.text:
            result["telegram"] = True
    except:
        pass
    
    time.sleep(0.3)
    
    try:
        fr_resp = requests.get(f"https://fragment.com/username/{username}", headers=headers, timeout=10)
        if "unavailable" in fr_resp.text.lower():
            result["fragment"] = True
    except:
        pass
    
    result["available"] = result["telegram"] and result["fragment"]
    return result

def get_quality_score(username: str) -> tuple:
    score = 10
    
    if len(username) > 8:
        score -= 2
    elif len(username) > 6:
        score -= 1
    
    if any(char.isdigit() for char in username):
        score -= 2
    
    if any(not char.isalnum() for char in username):
        score -= 3
    
    if len(set(username)) < 4:
        score -= 2
    
    if score >= 9:
        quality = "отличный"
    elif score >= 7:
        quality = "хороший"
    elif score >= 5:
        quality = "средний"
    else:
        quality = "низкий"
    
    read = "высокая" if score >= 9 else "хорошая" if score >= 7 else "средняя"
    if any(c.isdigit() for c in username) or any(not c.isalnum() for c in username):
        read = "средняя"
    if len(username) > 8:
        read = "низкая"
    
    return score, quality, read

# ========== ФУНКЦИИ ПЛАТЕЖЕЙ PLATEGA ==========

async def create_platega_invoice(user_id: int, days: int, amount: float, payment_method: str = "all"):
    """Создание платежа через Platega API"""
    if not PLATEGA_MERCHANT_ID or not PLATEGA_SECRET:
        logging.warning("PLATEGA_MERCHANT_ID или PLATEGA_SECRET не заданы")
        return None
    
    url = f"{PLATEGA_API_URL}api/v1/payment/create"
    
    order_id = f"premium_{user_id}_{days}_{int(time.time())}"
    
    # Определяем валюту в зависимости от способа оплаты
    if payment_method == "sbp":
        currency = "RUB"
    else:
        currency = "USD"
    
    payload = {
        "amount": str(amount),
        "currency": currency,
        "order_id": order_id,
        "description": f"Premium подписка на {days} дней",
        "success_url": f"https://t.me/{BOT_NAME}",
        "cancel_url": f"https://t.me/{BOT_NAME}",
        "webhook_url": get_webhook_url(),
        "metadata": {
            "user_id": user_id,
            "days": days,
            "type": "premium",
            "payment_method": payment_method
        }
    }
    
    # Добавляем параметры для СБП
    if payment_method == "sbp":
        payload["payment_methods"] = ["sbp"]
        payload["sbp_params"] = {
            "bank_name": "Все банки",
            "description": f"Оплата Premium на {days} дней"
        }
    elif payment_method == "crypto":
        payload["payment_methods"] = ["crypto"]
    
    headers = {
        "X-MerchantId": PLATEGA_MERCHANT_ID,
        "X-Secret": PLATEGA_SECRET,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        data = response.json()
        
        if data.get("success") or data.get("status") == "success":
            payment_url = data.get("payment_url") or data.get("url")
            payment_id = data.get("payment_id") or data.get("id")
            
            logging.info(f"Платёж создан: {payment_id}, URL: {payment_url}")
            logging.info(f"Webhook URL: {get_webhook_url()}")
            
            result = {
                "url": payment_url,
                "payment_id": payment_id,
                "order_id": order_id
            }
            
            if payment_method == "sbp":
                result["sbp_qr"] = data.get("sbp_qr") or data.get("qr_code")
                result["sbp_qr_url"] = data.get("sbp_qr_url")
            
            return result
        else:
            error = data.get("error", "Неизвестная ошибка")
            logging.error(f"Ошибка Platega: {error}, полный ответ: {data}")
            return None
    except Exception as e:
        logging.exception("Ошибка при создании платежа в Platega")
        return None

async def check_platega_payment(payment_id: str):
    """Проверка статуса платежа"""
    if not PLATEGA_MERCHANT_ID or not PLATEGA_SECRET:
        return None
    
    url = f"{PLATEGA_API_URL}api/v1/payment/status/{payment_id}"
    
    headers = {
        "X-MerchantId": PLATEGA_MERCHANT_ID,
        "X-Secret": PLATEGA_SECRET
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        data = response.json()
        
        return data
    except Exception as e:
        logging.exception("Ошибка при проверке платежа")
        return None

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========

@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    clear_waiting_state(user_id)
    
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = int(args[1].replace("ref_", ""))
        if referrer_id != user_id:
            referrer = await get_user(referrer_id)
            if referrer:
                invited = referrer.get('invited', 0) + 1
                attempts = referrer.get('attempts', 0) + 5
                await update_user(referrer_id, invited=invited, attempts=attempts)
    
    await create_user(user_id, username)
    
    is_subscribed = await check_subscription(user_id)
    
    if not is_subscribed:
        text = (
            "<b>Требуется подписка</b>\n\n"
            "Чтобы пользоваться Hunter, подпишитесь на каналы\n\n"
            "После подписки нажмите «Проверить подписки».\n\n"
            '<blockquote expandable="">'
            f"Официальный канал: {REQUIRED_CHANNEL}"
            "</blockquote>"
        )
        
        await safe_answer_photo(
            message,
            IMG_MENU,
            text,
            subscription_menu()
        )
        return
    
    was_reset = await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    if was_reset and user:
        await message.answer(
            "<b>Ваши бесплатные попытки восстановлены!</b>\n\n"
            f"Доступно: {user['attempts']} попыток на сегодня.\n\n"
            "Нажмите Поиск чтобы начать!",
            reply_markup=main_menu()
        )
    else:
        await safe_answer_photo(
            message,
            IMG_MENU,
            "<b>Добро пожаловать в Hunter!</b>\n\nВыберите действие:",
            main_menu()
        )

@dp.message(Command("admin"))
async def admin_command(message: Message):
    user_id = message.from_user.id
    
    clear_waiting_state(user_id)
    
    if not is_admin(user_id):
        await message.answer("У вас нет доступа к админ-панели.")
        return
    
    await message.answer(
        "<b>Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_menu()
    )

# ========== УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК СООБЩЕНИЙ ==========

@dp.message()
async def universal_message_handler(message: Message):
    if not message.text:
        return
    
    user_id = message.from_user.id
    text = message.text.strip()
    
    if user_id in admin_states:
        state = admin_states[user_id].get("action")
        if state == "broadcast":
            await broadcast_message_handler(message)
        elif state in ["give_premium", "remove_premium", "add_attempts"]:
            await admin_input_handler(message)
        else:
            del admin_states[user_id]
            await message.answer(
                "Действие отменено. Используйте /admin для доступа к панели.",
                reply_markup=back_to_menu()
            )
        return
    
    if user_id in waiting_for_words:
        await handle_words_input(message)
        return
    
    await safe_answer_photo(
        message,
        IMG_MENU,
        "<b>Добро пожаловать в Hunter!</b>\n\nВыберите действие:",
        main_menu()
    )

# ========== АДМИН-ОБРАБОТЧИКИ ==========

async def admin_input_handler(message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        return
    
    if user_id not in admin_states:
        return
    
    action = admin_states[user_id].get("action")
    text = message.text.strip()
    
    try:
        if action == "give_premium":
            target_id = int(text)
            user = await get_user(target_id)
            if not user:
                await message.answer(f"Пользователь с ID {target_id} не найден")
                return
            
            admin_states[user_id]["target_id"] = target_id
            await message.answer(
                f"Выберите количество дней для Premium пользователю {target_id}:",
                reply_markup=admin_premium_days_menu()
            )
            return
            
        elif action == "remove_premium":
            target_id = int(text)
            user = await get_user(target_id)
            if not user:
                await message.answer(f"Пользователь с ID {target_id} не найден")
                return
            
            await update_user(target_id, is_premium=False, premium_until=None)
            await log_admin_action(user_id, "remove_premium", target_id, "Premium забран")
            await message.answer(f"Premium забран у пользователя {target_id}")
            
        elif action == "add_attempts":
            parts = text.split()
            if len(parts) < 2:
                await message.answer("Неверный формат. Используйте: ID количество")
                return
            
            target_id = int(parts[0])
            amount = int(parts[1])
            
            user = await get_user(target_id)
            if not user:
                await message.answer(f"Пользователь с ID {target_id} не найден")
                return
            
            new_attempts = user['attempts'] + amount
            await update_user(target_id, attempts=new_attempts)
            await log_admin_action(user_id, "add_attempts", target_id, f"Добавлено {amount} попыток")
            await message.answer(f"Пользователю {target_id} добавлено {amount} попыток\nТеперь у него {new_attempts} попыток")
        
        await message.answer(
            "<b>Админ-панель</b>\n\n"
            "Выберите действие:",
            reply_markup=admin_menu()
        )
        del admin_states[user_id]
        
    except ValueError:
        await message.answer("Неверный формат ID. Введите число.")
    except Exception as e:
        logging.exception("Ошибка в админ-обработчике")
        await message.answer(f"Произошла ошибка: {e}")

async def broadcast_message_handler(message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        return
    
    if user_id not in admin_states or admin_states[user_id].get("action") != "broadcast":
        return
    
    text = message.text.strip()
    if not text:
        await message.answer("Введите текст для рассылки")
        return
    
    users = await get_all_users()
    success = 0
    failed = 0
    
    status_msg = await message.answer(f"Начинаю рассылку {len(users)} пользователям...")
    
    for user in users:
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text=f"<b>Объявление</b>\n\n{text}"
            )
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await log_admin_action(user_id, "broadcast", details=f"Отправлено {success}, ошибок {failed}")
    await status_msg.edit_text(f"Рассылка завершена!\nОтправлено: {success}\nОшибок: {failed}")
    
    del admin_states[user_id]
    
    await message.answer(
        "<b>Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_menu()
    )

async def handle_words_input(message: Message):
    if not message.text:
        return
    
    user_id = message.from_user.id
    text = message.text.strip()
    
    if user_id in waiting_for_words:
        waiting_for_words.remove(user_id)
    
    try:
        if "," in text:
            words = [w.strip().lower() for w in text.split(",") if w.strip()]
        else:
            words = [text.lower()]
        
        await update_filters(user_id, words=words)
        
        await message.answer(
            f"Слова добавлены: {', '.join(words)}",
            reply_markup=back_to_menu()
        )
    except Exception as e:
        logging.exception("Ошибка при обработке слов")
        await message.answer(
            "Произошла ошибка при добавлении слов. Попробуйте ещё раз.",
            reply_markup=back_to_menu()
        )

# ========== АДМИН-ОБРАБОТЧИКИ (CALLBACK) ==========

@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await safe_edit_text(
        callback.message,
        "<b>Админ-панель</b>\n\n"
        "Выберите действие:",
        admin_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_cancel")
async def admin_cancel_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in admin_states:
        del admin_states[user_id]
    
    await safe_edit_text(
        callback.message,
        "<b>Админ-панель</b>\n\n"
        "Выберите действие:",
        admin_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_premium_"))
async def admin_premium_days_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    if user_id not in admin_states or admin_states[user_id].get("action") != "give_premium":
        await callback.answer("Ошибка: действие не найдено", show_alert=True)
        return
    
    days = int(callback.data.replace("admin_premium_", ""))
    target_id = admin_states[user_id].get("target_id")
    
    if not target_id:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return
    
    try:
        await update_user(target_id, is_premium=True, premium_until=datetime.now() + timedelta(days=days))
        await log_admin_action(user_id, "give_premium", target_id, f"Premium выдан на {days} дней")
        
        await callback.message.delete()
        await callback.message.answer(
            f"Premium выдан пользователю {target_id} на {days} дней",
            reply_markup=admin_back()
        )
        
        try:
            await bot.send_message(
                chat_id=target_id,
                text=(
                    f"Вам выдан Premium на {days} дней!\n\n"
                    f"Действует до: {(datetime.now() + timedelta(days=days)).strftime('%d.%m.%Y %H:%M')}\n\n"
                    "Теперь у вас:\n"
                    "Неограниченные попытки\n"
                    "Приоритетная проверка\n"
                    "Доступ к магниту\n"
                    "Персональная поддержка"
                )
            )
        except Exception as e:
            logging.warning(f"Не удалось отправить уведомление пользователю {target_id}: {e}")
        
        del admin_states[user_id]
        
    except Exception as e:
        logging.exception("Ошибка при выдаче Premium")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    stats = await get_stats()
    
    text = (
        "<b>Статистика</b>\n\n"
        f"Всего пользователей: {stats['total']}\n"
        f"Активных (24ч): {stats['active']}\n"
        f"Premium: {stats['premium']}\n"
        f"Всего попыток: {stats['total_attempts']}\n"
        f"Среднее попыток: {stats['avg_attempts']}\n\n"
        f"Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    
    await safe_edit_text(
        callback.message,
        text,
        admin_back()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    users = await get_all_users()
    
    text = "<b>Последние 10 пользователей</b>\n\n"
    for i, user in enumerate(users[:10], 1):
        text += f"{i}. ID: {user['user_id']} | Попыток: {user['attempts']} | Premium: {'Да' if user['is_premium'] else 'Нет'}\n"
    
    text += f"\nВсего: {len(users)} пользователей"
    
    await safe_edit_text(
        callback.message,
        text,
        admin_back()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_give_premium")
async def admin_give_premium_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    admin_states[user_id] = {"action": "give_premium"}
    
    await safe_edit_text(
        callback.message,
        "<b>Выдать Premium</b>\n\n"
        "Введите ID пользователя, которому нужно выдать Premium:\n\n"
        "Пример: <code>123456789</code>",
        admin_cancel()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_remove_premium")
async def admin_remove_premium_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    admin_states[user_id] = {"action": "remove_premium"}
    
    await safe_edit_text(
        callback.message,
        "<b>Забрать Premium</b>\n\n"
        "Введите ID пользователя, у которого нужно забрать Premium:\n\n"
        "Пример: <code>123456789</code>",
        admin_cancel()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_add_attempts")
async def admin_add_attempts_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    admin_states[user_id] = {"action": "add_attempts"}
    
    await safe_edit_text(
        callback.message,
        "<b>Выдать запросы</b>\n\n"
        "Введите ID пользователя и количество запросов через пробел:\n\n"
        "Пример: <code>123456789 10</code>",
        admin_cancel()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_broadcast")
async def admin_broadcast_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    admin_states[user_id] = {"action": "broadcast"}
    
    await safe_edit_text(
        callback.message,
        "<b>Рассылка</b>\n\n"
        "Введите текст для рассылки всем пользователям:\n\n"
        "Просто отправьте сообщение с текстом",
        admin_cancel()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_refs")
async def admin_refs_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    users = await get_all_users()
    top_refs = sorted(users, key=lambda x: x['invited'], reverse=True)[:10]
    
    text = "<b>Топ рефералов</b>\n\n"
    for i, user in enumerate(top_refs, 1):
        text += f"{i}. ID: {user['user_id']} | Пригласил: {user['invited']}\n"
    
    await safe_edit_text(
        callback.message,
        text,
        admin_back()
    )
    await callback.answer()

# ========== ПРЕМИУМ ОБРАБОТЧИКИ ==========

@dp.callback_query(lambda c: c.data == "premium")
async def premium_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    clear_waiting_state(user_id)
    
    try:
        user = await get_user(user_id)
        is_premium = user['is_premium'] if user else False
        
        if is_premium and user.get('premium_until'):
            days_left = (user['premium_until'] - datetime.now()).days
            if days_left < 0:
                days_left = 0
            
            text = (
                f"У вас есть Premium\n\n"
                f"Осталось дней: {days_left}"
            )
        else:
            text = "Подписка Premium"
        
        await safe_answer_photo(
            callback.message,
            IMG_PREMIUM,
            text,
            premium_menu()
        )
        
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе премиум")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "premium_info")
async def premium_info_callback(callback: CallbackQuery):
    try:
        text = (
            "<b>Что входит в Premium</b>\n\n"
            "Безлимитный поиск юзернеймов\n"
            "Поиск с фильтрами без ожидания\n"
            "Поиск по заданным словам\n"
            "Ускоренная проверка вариантов\n"
            "Premium для друга"
        )
        
        await callback.message.delete()
        await callback.message.answer(
            text,
            reply_markup=back_to_menu()
        )
    except Exception as e:
        logging.exception("Ошибка при показе информации о Premium")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "buy_premium_choose")
async def buy_premium_choose_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    user = await get_user(user_id)
    is_premium = user['is_premium'] if user else False
    
    if is_premium and user.get('premium_until'):
        days_left = (user['premium_until'] - datetime.now()).days
        if days_left < 0:
            days_left = 0
        
        await callback.message.delete()
        await callback.message.answer(
            f"<b>У вас есть Premium</b>\n\n"
            f"Осталось дней: {days_left}",
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    await callback.message.delete()
    await callback.message.answer(
        "Выберите способ оплаты:",
        reply_markup=buy_premium_choose_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "buy_premium_usd_choose")
async def buy_premium_usd_choose_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Выберите срок подписки. Оплата в USD (криптовалюта):",
        reply_markup=buy_premium_usd_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "buy_premium_rub_choose")
async def buy_premium_rub_choose_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Выберите срок подписки. Оплата через СБП (рубли):",
        reply_markup=buy_premium_rub_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("usd_"))
async def usd_payment_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    days = int(callback.data.replace("usd_", ""))
    
    prices = {
        1: 1.00,
        3: 2.00,
        7: 3.00,
        30: 5.00
    }
    
    amount = prices.get(days, 1.00)
    
    invoice = await create_platega_invoice(user_id, days, amount, payment_method="crypto")
    
    if not invoice:
        await callback.answer(
            "Ошибка при создании платежа. Попробуйте позже или выберите другой способ оплаты.",
            show_alert=True
        )
        return
    
    text = (
        f"Оплата Premium на {days} дней\n\n"
        f"Сумма: {amount} USD\n"
        f"Способ: криптовалюта\n\n"
        "После оплаты Premium активируется автоматически"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить", url=invoice["url"])],
        [InlineKeyboardButton(text="Проверить оплату", callback_data=f"check_payment_usd_{invoice['payment_id']}_{days}_{user_id}")],
        [InlineKeyboardButton(text="Назад", callback_data="buy_premium_usd_choose")]
    ])
    
    await callback.message.delete()
    await callback.message.answer(
        text,
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("rub_"))
async def rub_payment_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    days = int(callback.data.replace("rub_", ""))
    
    prices = {
        1: 29,
        3: 50,
        7: 99,
        30: 149
    }
    
    amount = prices.get(days, 29)
    
    invoice = await create_platega_invoice(user_id, days, amount, payment_method="sbp")
    
    if not invoice:
        await callback.answer(
            "Ошибка при создании платежа. Попробуйте позже или выберите другой способ оплаты.",
            show_alert=True
        )
        return
    
    text = (
        f"Оплата Premium на {days} дней\n\n"
        f"Сумма: {amount} ₽\n"
        f"Способ: СБП\n\n"
        "Как оплатить:\n"
        "1. Нажмите Оплатить через СБП\n"
        "2. Отсканируйте QR-код в приложении банка\n"
        "3. Подтвердите платеж\n\n"
        "После оплаты Premium активируется автоматически"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить через СБП", url=invoice["url"])],
        [InlineKeyboardButton(text="Показать QR-код", callback_data=f"show_qr_{invoice['payment_id']}")],
        [InlineKeyboardButton(text="Проверить оплату", callback_data=f"check_payment_rub_{invoice['payment_id']}_{days}_{user_id}")],
        [InlineKeyboardButton(text="Назад", callback_data="buy_premium_rub_choose")]
    ])
    
    await callback.message.delete()
    await callback.message.answer(
        text,
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("check_payment_usd_"))
async def check_usd_payment_callback(callback: CallbackQuery):
    data = callback.data.replace("check_payment_usd_", "").split("_")
    payment_id = data[0]
    days = int(data[1])
    user_id = int(data[2])
    
    await callback.answer("Проверяем статус платежа...")
    
    status = await check_platega_payment(payment_id)
    
    if not status:
        await callback.message.answer(
            "Не удалось проверить статус платежа. Попробуйте позже.",
            reply_markup=back_to_menu()
        )
        return
    
    payment_status = status.get("status") or status.get("payment_status")
    
    if payment_status == "paid" or payment_status == "success" or status.get("paid") == True:
        new_until = await extend_premium(user_id, days)
        
        if new_until:
            await log_admin_action(
                user_id,
                "buy_premium_usd",
                details=f"Premium на {days} дней через USD (крипта). Payment: {payment_id}"
            )
            
            await callback.message.delete()
            await callback.message.answer(
                f"Premium активирован на {days} дней!\n\n"
                f"Действует до: {new_until.strftime('%d.%m.%Y %H:%M')}\n\n"
                "Теперь у вас:\n"
                "Неограниченные попытки\n"
                "Приоритетная проверка\n"
                "Доступ к магниту\n"
                "Персональная поддержка",
                reply_markup=main_menu()
            )
        else:
            await callback.message.answer(
                "Ошибка при активации Premium. Свяжитесь с поддержкой.",
                reply_markup=back_to_menu()
            )
    else:
        await callback.message.answer(
            "Платёж ещё не обработан.\n"
            "Пожалуйста, завершите оплату и нажмите Проверить оплату снова.\n\n"
            "Если вы уже оплатили, подождите 1-2 минуты.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Проверить снова", callback_data=callback.data)],
                [InlineKeyboardButton(text="Назад", callback_data="buy_premium_usd_choose")]
            ])
        )

@dp.callback_query(lambda c: c.data.startswith("check_payment_rub_"))
async def check_rub_payment_callback(callback: CallbackQuery):
    data = callback.data.replace("check_payment_rub_", "").split("_")
    payment_id = data[0]
    days = int(data[1]) if len(data) > 1 and data[1] != '0' else None
    user_id = int(data[2]) if len(data) > 2 and data[2] != '0' else callback.from_user.id
    
    if days is None:
        await callback.answer("Данные о платеже не найдены", show_alert=True)
        return
    
    await callback.answer("Проверяем статус платежа...")
    
    status = await check_platega_payment(payment_id)
    
    if not status:
        await callback.message.answer(
            "Не удалось проверить статус платежа. Попробуйте позже.",
            reply_markup=back_to_menu()
        )
        return
    
    payment_status = status.get("status") or status.get("payment_status")
    
    if payment_status == "paid" or payment_status == "success" or status.get("paid") == True:
        new_until = await extend_premium(user_id, days)
        
        if new_until:
            await log_admin_action(
                user_id,
                "buy_premium_sbp",
                details=f"Premium на {days} дней через СБП. Payment: {payment_id}"
            )
            
            await callback.message.delete()
            await callback.message.answer(
                f"Premium активирован на {days} дней!\n\n"
                f"Действует до: {new_until.strftime('%d.%m.%Y %H:%M')}\n\n"
                "Теперь у вас:\n"
                "Неограниченные попытки\n"
                "Приоритетная проверка\n"
                "Доступ к магниту\n"
                "Персональная поддержка",
                reply_markup=main_menu()
            )
        else:
            await callback.message.answer(
                "Ошибка при активации Premium. Свяжитесь с поддержкой.",
                reply_markup=back_to_menu()
            )
    else:
        await callback.message.answer(
            "Платёж ещё не обработан.\n\n"
            "Пожалуйста, завершите оплату через СБП и нажмите Проверить оплату снова.\n\n"
            "Обычно платеж обрабатывается в течение 1-2 минут.\n\n"
            "Если вы уже оплатили, подождите немного и попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Проверить снова", callback_data=callback.data)],
                [InlineKeyboardButton(text="QR-код", callback_data=f"show_qr_{payment_id}")],
                [InlineKeyboardButton(text="Назад", callback_data="buy_premium_rub_choose")]
            ])
        )

@dp.callback_query(lambda c: c.data.startswith("show_qr_"))
async def show_qr_callback(callback: CallbackQuery):
    payment_id = callback.data.replace("show_qr_", "")
    
    try:
        payment_info = await check_platega_payment(payment_id)
        
        if payment_info and payment_info.get("qr_code"):
            qr_url = payment_info.get("qr_code")
            
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=qr_url,
                caption=(
                    "QR-код для оплаты через СБП\n\n"
                    "Отсканируйте QR-код в приложении вашего банка\n"
                    "Сумма к оплате будет указана автоматически"
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Проверить оплату", callback_data=f"check_payment_rub_{payment_id}_0_0")],
                    [InlineKeyboardButton(text="Назад", callback_data="buy_premium_rub_choose")]
                ])
            )
        else:
            await callback.answer("QR-код не найден. Используйте кнопку Оплатить через СБП", show_alert=True)
    except Exception as e:
        logging.exception("Ошибка при показе QR-кода")
        await callback.answer("Ошибка при загрузке QR-кода", show_alert=True)
    finally:
        await callback.answer()

# ========== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ==========

@dp.callback_query(lambda c: c.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        await callback.message.delete()
        await callback.message.answer(
            "<b>Подписка подтверждена!</b>\n\n"
            "Теперь вы можете пользоваться ботом.",
            reply_markup=main_menu()
        )
    else:
        text = (
            "<b>Требуется подписка</b>\n\n"
            "Чтобы пользоваться Hunter, подпишитесь на каналы\n\n"
            "После подписки нажмите «Проверить подписки».\n\n"
            '<blockquote expandable="">'
            f"Официальный канал: {REQUIRED_CHANNEL}"
            "</blockquote>"
        )
        
        await safe_edit_text(
            callback.message,
            text,
            subscription_menu()
        )
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "menu")
async def menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    clear_waiting_state(user_id)
    
    is_subscribed = await check_subscription(user_id)
    
    if not is_subscribed:
        text = (
            "<b>Требуется подписка</b>\n\n"
            "Чтобы пользоваться Hunter, подпишитесь на каналы\n\n"
            "После подписки нажмите «Проверить подписки».\n\n"
            '<blockquote expandable="">'
            f"Официальный канал: {REQUIRED_CHANNEL}"
            "</blockquote>"
        )
        
        await safe_answer_photo(
            callback.message,
            IMG_MENU,
            text,
            subscription_menu()
        )
        await callback.message.delete()
        await callback.answer()
        return
    
    await reset_attempts_if_needed(user_id)
    
    try:
        await safe_answer_photo(
            callback.message,
            IMG_MENU,
            "<b>Добро пожаловать в Hunter!</b>\n\nВыберите действие:",
            main_menu()
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при возврате в меню")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "search")
async def search_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    clear_waiting_state(user_id)
    
    is_subscribed = await check_subscription(user_id)
    
    if not is_subscribed:
        text = (
            "<b>Требуется подписка</b>\n\n"
            "Чтобы пользоваться Hunter, подпишитесь на каналы\n\n"
            "После подписки нажмите «Проверить подписки».\n\n"
            '<blockquote expandable="">'
            f"Официальный канал: {REQUIRED_CHANNEL}"
            "</blockquote>"
        )
        
        await safe_answer_photo(
            callback.message,
            IMG_MENU,
            text,
            subscription_menu()
        )
        await callback.message.delete()
        await callback.answer()
        return
    
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    if not user or user['attempts'] <= 0:
        await callback.message.answer(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    try:
        await safe_answer_photo(
            callback.message,
            IMG_SEARCH,
            "<b>Поиск</b>\n\nВыберите раздел ниже:",
            search_options_menu()
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе поиска")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "search_filters")
async def search_filters_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    clear_waiting_state(user_id)
    
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)

    if not user or user['attempts'] <= 0:
        await callback.message.answer(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return

    try:
        filters = await get_filters(user_id)
        words_text = 'не добавлены' if not filters['words'] else ', '.join(filters['words'])

        text = (
            "<b>Настройка поиска</b>\n\n"
            "Текущие параметры:\n\n"
            f"Длина: <b>{filters['length']} символов</b>\n"
            f"Символы: <b>{filters['chars']}</b>\n"
            f"Генерация: <b>{filters['generation']}</b>\n"
            f"Слова: <b>{words_text}</b>\n\n"
            "Доступ: <b>бесплатный запуск доступен</b>\n"
            "Обычным пользователям доступен 1 запуск в 24 часа."
        )

        await safe_answer_photo(
            callback.message,
            IMG_FILTERS,
            text,
            filters_menu()
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе фильтров")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "filter_length")
async def filter_length_callback(callback: CallbackQuery):
    try:
        await safe_edit_text(
            callback.message,
            "<b>Выберите длину</b>\n\n"
            "Выберите длину юзернейма:",
            filter_length_menu()
        )
    except Exception as e:
        logging.exception("Ошибка при выборе длины")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("filter_len_"))
async def filter_length_set_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    length = int(callback.data.split("_")[2])
    
    try:
        await update_filters(user_id, length=length)
        await callback.answer(f"Длина установлена: {length} символов", show_alert=True)
        await search_filters_callback(callback)
    except Exception as e:
        logging.exception("Ошибка при установке длины")

@dp.callback_query(lambda c: c.data == "filter_chars")
async def filter_chars_callback(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Только буквы", callback_data="filter_char_letters")],
        [InlineKeyboardButton(text="Буквы и цифры", callback_data="filter_char_letters_digits")],
        [InlineKeyboardButton(text="Назад", callback_data="search_filters")]
    ])
    
    try:
        await safe_edit_text(
            callback.message,
            "<b>Изменить символы</b>\n\n"
            "Выберите тип символов:",
            keyboard
        )
    except Exception as e:
        logging.exception("Ошибка при выборе символов")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("filter_char_"))
async def filter_chars_set_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    chars_type = callback.data.replace("filter_char_", "")
    
    mapping = {
        "letters": "только буквы",
        "letters_digits": "буквы и цифры"
    }
    
    try:
        await update_filters(user_id, chars=mapping.get(chars_type, "только буквы"), chars_type=chars_type)
        await callback.answer(f"Символы: {mapping.get(chars_type, 'только буквы')}", show_alert=True)
        await search_filters_callback(callback)
    except Exception as e:
        logging.exception("Ошибка при установке символов")

@dp.callback_query(lambda c: c.data == "filter_generation")
async def filter_generation_callback(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Читаемые сочетания", callback_data="filter_gen_readable")],
        [InlineKeyboardButton(text="Случайные", callback_data="filter_gen_random")],
        [InlineKeyboardButton(text="Назад", callback_data="search_filters")]
    ])
    
    try:
        await safe_edit_text(
            callback.message,
            "<b>Изменить тип генерации</b>\n\n"
            "Выберите способ генерации:",
            keyboard
        )
    except Exception as e:
        logging.exception("Ошибка при выборе генерации")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("filter_gen_"))
async def filter_generation_set_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    gen_type = callback.data.replace("filter_gen_", "")
    
    mapping = {
        "readable": "читаемые сочетания",
        "random": "случайные"
    }
    
    try:
        await update_filters(user_id, generation=mapping.get(gen_type, "читаемые сочетания"))
        await callback.answer(f"Генерация: {mapping.get(gen_type, 'читаемые сочетания')}", show_alert=True)
        await search_filters_callback(callback)
    except Exception as e:
        logging.exception("Ошибка при установке генерации")

@dp.callback_query(lambda c: c.data == "filter_words")
async def filter_words_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    waiting_for_words.add(user_id)
    
    await safe_edit_text(
        callback.message,
        "<b>Добавить слова</b>\n\n"
        "Отправьте список слов через запятую.\n"
        "Например: game, boss, sky, pro\n\n"
        "Бот будет использовать эти слова для генерации.",
        back_to_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "filter_start")
async def filter_start_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    if not user or user['attempts'] <= 0:
        await callback.message.answer(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    try:
        filters = await get_filters(user_id)
        await callback.message.delete()
        await start_search_with_animation(callback.message, user_id, dict(filters), is_filter=True)
    except Exception as e:
        logging.exception("Ошибка при запуске поиска из фильтров")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "filter_reset")
async def filter_reset_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    try:
        await update_filters(user_id, length=6, chars="только буквы", chars_type="letters", generation="читаемые сочетания", words=[])
        await callback.answer("Настройки сброшены", show_alert=True)
        await search_filters_callback(callback)
    except Exception as e:
        logging.exception("Ошибка при сбросе настроек")

@dp.callback_query(lambda c: c.data == "search_5")
async def search_5_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    if not user or user['attempts'] <= 0:
        await callback.message.answer(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    await show_chars_selection(callback, user_id, 5)

@dp.callback_query(lambda c: c.data == "search_6")
async def search_6_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    if not user or user['attempts'] <= 0:
        await callback.message.answer(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    await show_chars_selection(callback, user_id, 6)

@dp.callback_query(lambda c: c.data == "search_magnet")
async def magnet_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    is_premium = user['is_premium'] if user else False
    
    if not is_premium:
        text = (
            "<b>Магнит</b>\n\n"
            "Магнит доступен только с активной Premium-подпиской."
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="OK", callback_data="menu")]
        ])
        
        await safe_answer_photo(
            callback.message,
            IMG_MAGNET,
            text,
            keyboard
        )
        await callback.message.delete()
        await callback.answer()
        return
    
    try:
        await safe_answer_photo(
            callback.message,
            IMG_MAGNET,
            "<b>Магнит</b>\n\n"
            "<b>Обычный</b> - стандартная скорость\n"
            "<b>Fast</b> - быстрая скорость\n"
            "<b>Mythoc</b> - максимальная скорость",
            magnet_menu()
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе магнита")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("magnet_"))
async def magnet_action_callback(callback: CallbackQuery):
    mode = callback.data.replace("magnet_", "")
    user_id = callback.from_user.id
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    is_premium = user['is_premium'] if user else False
    
    if not is_premium:
        await callback.message.answer(
            "<b>Магнит доступен только с Premium</b>",
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    if not user or user['attempts'] <= 0:
        await callback.message.answer(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    try:
        mode_names = {
            "normal": "Обычный",
            "fast": "Fast",
            "mythoc": "Mythoc"
        }
        mode_name = mode_names.get(mode, mode)
        
        filters = await get_filters(user_id)
        filters['length'] = 6
        
        await callback.message.delete()
        await start_search_with_animation(callback.message, user_id, dict(filters), is_magnet=True)
    except Exception as e:
        logging.exception("Ошибка при запуске магнита")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_search")
async def cancel_search_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Поиск отменён",
        reply_markup=back_to_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "chars_letters")
async def chars_letters_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    length = await get_pending_length(user_id)
    chars_type = "letters"
    chars_name = "только буквы"
    
    await callback.message.delete()
    await do_search_with_animation(callback.message, user_id, length, chars_type, chars_name)

@dp.callback_query(lambda c: c.data == "chars_letters_digits")
async def chars_letters_digits_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    length = await get_pending_length(user_id)
    chars_type = "letters_digits"
    chars_name = "буквы и цифры"
    
    await callback.message.delete()
    await do_search_with_animation(callback.message, user_id, length, chars_type, chars_name)

@dp.callback_query(lambda c: c.data == "favorite")
async def favorite_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    username = user['username'] if user else None
    
    try:
        if username:
            await add_favorite(user_id, username)
            await callback.answer(f"@{username} добавлен в избранное!", show_alert=True)
        else:
            await callback.answer("Нет юзернейма для добавления", show_alert=True)
    except Exception as e:
        logging.exception("Ошибка при добавлении в избранное")

@dp.callback_query(lambda c: c.data == "clear_favorites")
async def clear_favorites_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    try:
        await clear_favorites(user_id)
        await callback.answer("Избранное очищено!", show_alert=True)
        await profile_callback(callback)
    except Exception as e:
        logging.exception("Ошибка при очистке избранного")

@dp.callback_query(lambda c: c.data == "profile")
async def profile_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    clear_waiting_state(user_id)
    
    await reset_attempts_if_needed(user_id)
    
    try:
        user = await get_user(user_id)
        if not user:
            await create_user(user_id)
            user = await get_user(user_id)
        
        favorites = await get_favorites(user_id)
        tg_user = await bot.get_chat(user_id)
        tg_username = tg_user.username if tg_user.username else "не установлен"
        
        status = "Premium" if user['is_premium'] else "Обычный"
        
        profile_text = (
            f"<b>Ваш профиль</b>\n"
            f"ID: {user_id}\n"
            f"Telegram: @{tg_username}\n"
            f"Статус: {status}\n"
            f"Количество попыток: {user['attempts']}\n\n"
            f"Приглашено друзей: {user['invited']}"
        )
        
        await safe_answer_photo(
            callback.message,
            IMG_PROFILE,
            profile_text,
            profile_menu(len(favorites))
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе профиля")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "favorites_list")
async def favorites_list_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    favorites = await get_favorites(user_id)
    
    try:
        if favorites:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            for username in favorites:
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text=f"@{username}", callback_data=f"fav_{username}")
                ])
            keyboard.inline_keyboard.append([
                [InlineKeyboardButton(text="Мой профиль", callback_data="profile_from_favorites")]
            ])
            
            text = (
                f"<b>Избранные юзернеймы</b>\n\n"
                f"Сохранено: {len(favorites)} · Страница 1/1\n"
                "Нажмите на ник, чтобы открыть его карточку."
            )
            
            await callback.message.delete()
            await callback.message.answer(
                text,
                reply_markup=keyboard
            )
        else:
            await callback.message.delete()
            await callback.message.answer(
                "<b>Избранные юзернеймы</b>\n\n"
                "У вас пока нет избранных юзернеймов.",
                reply_markup=back_to_menu()
            )
    except Exception as e:
        logging.exception("Ошибка при показе избранного")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("fav_"))
async def favorite_username_callback(callback: CallbackQuery):
    username = callback.data.replace("fav_", "")
    
    try:
        text = (
            f"<b>@{username}</b>\n\n"
            "Мой профиль"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="favorites_list")]
        ])
        
        await callback.message.delete()
        await callback.message.answer(
            text,
            reply_markup=keyboard
        )
    except Exception as e:
        logging.exception("Ошибка при показе юзернейма")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "profile_from_favorites")
async def profile_from_favorites_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await reset_attempts_if_needed(user_id)
    
    try:
        user = await get_user(user_id)
        if not user:
            await create_user(user_id)
            user = await get_user(user_id)
        
        favorites = await get_favorites(user_id)
        tg_user = await bot.get_chat(user_id)
        tg_username = tg_user.username if tg_user.username else "не установлен"
        
        status = "Premium" if user['is_premium'] else "Обычный"
        
        profile_text = (
            f"<b>Ваш профиль</b>\n"
            f"ID: {user_id}\n"
            f"Telegram: @{tg_username}\n"
            f"Статус: {status}\n"
            f"Количество попыток: {user['attempts']}\n\n"
            f"Приглашено друзей: {user['invited']}"
        )
        
        await callback.message.delete()
        await callback.message.answer(
            profile_text,
            reply_markup=profile_menu(len(favorites))
        )
    except Exception as e:
        logging.exception("Ошибка при показе профиля")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "info")
async def info_callback(callback: CallbackQuery):
    try:
        text = (
            "<b>Информация</b>\n\n"
            "Hunter - бот для поиска свободных юзернеймов\n\n"
            "Проверка на t.me и fragment.com\n"
            "Оценка качества юзернеймов\n"
            "3 попытки бесплатно каждый день\n"
            "Приглашай друзей и получай бонусы!\n\n"
            "Документы и официальные материалы Hunter:\n"
            "<a href='https://telegra.ph/Polzovatelskoe-soglashenie-08-27-60'>Пользовательское соглашение</a>\n"
            "<a href='https://telegra.ph/Politika-konfidencialnosti-08-27-84'>Политика конфиденциальности</a>\n\n"
            "Версия: 1.0"
        )
        
        info_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Официальный канал", url="https://t.me/huntergoaj")],
            [InlineKeyboardButton(text="В меню", callback_data="menu")]
        ])
        
        await safe_edit_text(
            callback.message,
            text,
            info_keyboard
        )
    except Exception as e:
        logging.exception("Ошибка при показе информации")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "referrals")
async def referrals_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    clear_waiting_state(user_id)
    
    try:
        user = await get_user(user_id)
        if not user:
            await create_user(user_id)
            user = await get_user(user_id)
        
        bot_username = (await bot.get_me()).username
        invited = user['invited'] if user else 0
        
        text = (
            f"<b>Рефералы</b>\n"
            f"Приглашено друзей: {invited}\n\n"
            '<blockquote expandable="">'
            "2 друга - 2 попытки\n"
            "4 друга - 6 попыток\n"
            "6 друзей - 10 попыток\n"
            "Дальше каждые 2 друга - ещё 4 попытки"
            "</blockquote>\n\n"
            f"<b>Ваша реферальная ссылка:</b>\n"
            f"https://t.me/{bot_username}?start=ref_{user_id}"
        )
        
        await safe_answer_photo(
            callback.message,
            IMG_REFERRALS,
            text,
            referrals_menu()
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе рефералов")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "support")
async def support_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    clear_waiting_state(user_id)
    
    try:
        text = (
            "<b>Поддержка</b>\n\n"
            "По любой помощи и вопросам пиши нам - ответим и поможем"
        )
        
        await safe_answer_photo(
            callback.message,
            IMG_SUPPORT,
            text,
            support_menu()
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе поддержки")
    finally:
        await callback.answer()

# ========== ФУНКЦИИ ПОИСКА С КАРТИНКОЙ ==========

async def show_chars_selection(callback: CallbackQuery, user_id: int, length: int):
    try:
        await set_pending_length(user_id, length)
        
        await callback.message.delete()
        await safe_answer_photo(
            callback.message,
            IMG_SEARCH,
            "<b>Какие символы использовать?</b>\n\n"
            "Выберите один из вариантов - бот учтёт его при поиске свободного юзернейма.",
            chars_menu()
        )
    except Exception as e:
        logging.exception("Ошибка при выборе символов")
    finally:
        await callback.answer()

async def start_search_with_animation(message: types.Message, user_id: int, filters: dict, is_filter: bool = False, is_magnet: bool = False):
    try:
        is_premium = False
        user = await get_user(user_id)
        if user:
            is_premium = user['is_premium']

        def build_caption(current_username):
            checking_line = f"@{current_username}" if current_username else "..."
            return (
                "    Ищу свободный юзернейм для тебя\n\n"
                f"    Проверяю сейчас: {checking_line}\n\n"
                '<blockquote>    Обычный поиск | Hunter</blockquote>'
            )

        status_msg = await message.answer_photo(
            IMG_SEARCH,
            caption=build_caption(None),
            reply_markup=search_progress_menu()
        )

        found_username = None
        attempts = 0
        max_attempts = 50 if is_premium else 20

        while attempts < max_attempts:
            if filters.get("words") and len(filters.get("words", [])) > 0:
                username = random.choice(filters["words"]).lower()
                if len(username) < filters.get("length", 6):
                    username = generate_username(filters.get("length", 6), filters.get("chars_type", "letters"))
            else:
                username = generate_username(filters.get("length", 6), filters.get("chars_type", "letters"))

            await status_msg.edit_caption(
                caption=build_caption(username),
                reply_markup=search_progress_menu()
            )

            result = check_username(username)
            attempts += 1

            if result["available"]:
                found_username = username
                break

            await asyncio.sleep(0.3)

        if not is_premium and user:
            new_attempts = user['attempts'] - 1
            if new_attempts < 0:
                new_attempts = 0
            await update_user(user_id, attempts=new_attempts)
            attempts_left = new_attempts
        else:
            attempts_left = '∞'

        if found_username:
            await update_user(user_id, username=found_username)
            score, quality, read = get_quality_score(found_username)
            has_digits = "с цифрами" if any(c.isdigit() for c in found_username) else "без цифр"

            text = (
                f"<b>Юзернейм найден</b>\n\n"
                f"Юзернейм: @{found_username}\n"
                '<blockquote expandable="">'
                f"Качество: {score}/10 - {quality}\n"
                f"Читаемость: {read} · {has_digits} · длина: {len(found_username)}"
                "</blockquote>\n\n"
                f"Осталось попыток: {attempts_left}"
            )

            await status_msg.delete()
            await safe_answer_photo(
                message,
                IMG_RESULT,
                text,
                search_result_menu()
            )
        else:
            text = (
                f"<b>Юзернейм не найден</b>\n\n"
                f"Свободных юзернеймов не найдено.\n\n"
                f"Длина: {filters.get('length', 6)}\n"
                f"Символы: {filters.get('chars', 'только буквы')}\n"
                f"Осталось попыток: {attempts_left}"
            )

            await status_msg.edit_caption(
                caption=text,
                reply_markup=search_result_menu()
            )
    except Exception as e:
        logging.exception("Ошибка при поиске с анимацией")

async def do_search_with_animation(message: types.Message, user_id: int, length: int, chars_type: str, chars_name: str):
    try:
        is_premium = False
        user = await get_user(user_id)
        if user:
            is_premium = user['is_premium']

        def build_caption(current_username):
            checking_line = f"@{current_username}" if current_username else "..."
            return (
                "    Ищу свободный юзернейм для тебя\n\n"
                f"    Проверяю сейчас: {checking_line}\n\n"
                '<blockquote>    Обычный поиск | Hunter</blockquote>'
            )

        status_msg = await message.answer_photo(
            IMG_SEARCH,
            caption=build_caption(None),
            reply_markup=search_progress_menu()
        )

        found_username = None
        attempts = 0
        max_attempts = 50 if is_premium else 20

        while attempts < max_attempts:
            username = generate_username(length, chars_type)

            await status_msg.edit_caption(
                caption=build_caption(username),
                reply_markup=search_progress_menu()
            )

            result = check_username(username)
            attempts += 1

            if result["available"]:
                found_username = username
                break

            await asyncio.sleep(0.3)

        if not is_premium and user:
            new_attempts = user['attempts'] - 1
            if new_attempts < 0:
                new_attempts = 0
            await update_user(user_id, attempts=new_attempts)
            attempts_left = new_attempts
        else:
            attempts_left = '∞'

        if found_username:
            await update_user(user_id, username=found_username)
            score, quality, read = get_quality_score(found_username)
            has_digits = "с цифрами" if any(c.isdigit() for c in found_username) else "без цифр"

            text = (
                f"<b>Юзернейм найден</b>\n\n"
                f"Юзернейм: @{found_username}\n"
                '<blockquote expandable="">'
                f"Качество: {score}/10 - {quality}\n"
                f"Читаемость: {read} · {has_digits} · длина: {length}"
                "</blockquote>\n\n"
                f"Осталось попыток: {attempts_left}"
            )

            await status_msg.delete()
            await safe_answer_photo(
                message,
                IMG_RESULT,
                text,
                search_result_menu()
            )
        else:
            text = (
                f"<b>Юзернейм не найден</b>\n\n"
                f"Свободных юзернеймов не найдено.\n\n"
                f"Длина: {length}\n"
                f"Символы: {chars_name}\n"
                f"Осталось попыток: {attempts_left}"
            )

            await status_msg.edit_caption(
                caption=text,
                reply_markup=search_result_menu()
            )
    except Exception as e:
        logging.exception("Ошибка при поиске с анимацией")

# ========== ВЕБХУК ДЛЯ PLATEGA ==========

async def platega_webhook(request):
    """Обработка вебхуков от Platega"""
    try:
        raw_body = await request.read()
        data = await request.json()
        
        logging.info(f"Получен вебхук от Platega: {data}")
        
        event = data.get("event")
        payment = data.get("payment", {})
        metadata = payment.get("metadata", {})
        
        if event == "payment.success" or payment.get("status") == "paid" or payment.get("status") == "success":
            order_id = payment.get("order_id")
            payment_id = payment.get("id")
            
            if not payment_id:
                return web.Response(text="OK", status=200)
            
            is_new = await mark_invoice_processed(payment_id)
            if not is_new:
                logging.info(f"Платёж {payment_id} уже обработан, пропускаем")
                return web.Response(text="OK", status=200)
            
            if metadata:
                user_id = int(metadata.get("user_id", 0))
                days = int(metadata.get("days", 30))
                payment_method = metadata.get("payment_method", "unknown")
            else:
                parts = order_id.split("_")
                if len(parts) >= 3:
                    user_id = int(parts[1])
                    days = int(parts[2])
                    payment_method = "unknown"
                else:
                    logging.warning(f"Не удалось распарсить order_id: {order_id}")
                    return web.Response(text="OK", status=200)
            
            if user_id:
                new_until = await extend_premium(user_id, days)
                
                if new_until:
                    method_name = "USD (крипта)" if payment_method == "crypto" else "СБП" if payment_method == "sbp" else "неизвестно"
                    
                    await log_admin_action(
                        user_id,
                        "buy_premium_platega_webhook",
                        details=f"Premium на {days} дней через {method_name}. Payment: {payment_id}"
                    )
                    
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=(
                                f"Premium активирован на {days} дней!\n\n"
                                f"Действует до: {new_until.strftime('%d.%m.%Y %H:%M')}\n\n"
                                "Теперь у вас:\n"
                                "Неограниченные попытки\n"
                                "Приоритетная проверка\n"
                                "Доступ к магниту\n"
                                "Персональная поддержка"
                            ),
                            reply_markup=main_menu()
                        )
                    except Exception as e:
                        logging.warning(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        
        return web.Response(text="OK", status=200)
    except Exception as e:
        logging.exception("Ошибка при обработке вебхука от Platega")
        return web.Response(text="ERROR", status=500)

# ========== HEALTH CHECK ==========

async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_post('/platega_webhook', platega_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"Health check server started on port {PORT}")
    logging.info(f"Webhook URL для Platega: {get_webhook_url()}")

# ========== ЗАПУСК ==========

async def main():
    asyncio.create_task(start_web_server())
    await init_db()
    print(f"{BOT_NAME} bot started!")
    logging.info(f"Webhook URL: {get_webhook_url()}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
