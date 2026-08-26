import logging
import time
import asyncio
import requests
import random
import string
import os
import asyncpg
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ParseMode

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_NAME = "Hunter"
SUPPORT_USERNAME = "crytcore"

# ========== ПРЯМЫЕ ССЫЛКИ НА КАРТИНКИ ==========
IMG_MENU = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21400"
IMG_SEARCH = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21404"
IMG_PREMIUM = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21408"
IMG_REFERRALS = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21402"
IMG_RESULT = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21406"
IMG_PROFILE = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21421"
IMG_MAGNET = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21412"
IMG_FILTERS = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21414"
IMG_SUPPORT = "https://res.cloudinary.com/o56i4fjt/image/upload/f_auto,q_auto/21416"

# ========== ЗАПАСНАЯ КАРТИНКА ==========
IMG_FALLBACK = "https://i.ibb.co/your-fallback-image.jpg"

# ========== ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ (PostgreSQL) ==========
DATABASE_URL = os.getenv("DATABASE_URL")

async def init_db():
    """Инициализация базы данных"""
    conn = await asyncpg.connect(DATABASE_URL)
    
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            username TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
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
    
    await conn.close()
    logging.info("База данных инициализирована")

async def get_user(user_id: int):
    """Получить пользователя из БД"""
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
    await conn.close()
    return user

async def create_user(user_id: int, username: str = None):
    """Создать пользователя в БД"""
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        INSERT INTO users (user_id, username, attempts, max_attempts, last_reset)
        VALUES ($1, $2, 3, 3, NOW())
        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
    ''', user_id, username)
    await conn.close()

async def update_user(user_id: int, **kwargs):
    """Обновить данные пользователя"""
    conn = await asyncpg.connect(DATABASE_URL)
    set_clause = ', '.join([f"{key} = ${i+2}" for i, key in enumerate(kwargs.keys())])
    values = [user_id] + list(kwargs.values())
    await conn.execute(f'UPDATE users SET {set_clause} WHERE user_id = $1', *values)
    await conn.close()

async def reset_attempts_if_needed(user_id: int):
    """Проверяет и сбрасывает попытки если прошло больше суток"""
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

async def get_favorites(user_id: int):
    """Получить избранное пользователя"""
    conn = await asyncpg.connect(DATABASE_URL)
    favorites = await conn.fetch('SELECT username FROM favorites WHERE user_id = $1', user_id)
    await conn.close()
    return [f['username'] for f in favorites]

async def add_favorite(user_id: int, username: str):
    """Добавить в избранное"""
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        INSERT INTO favorites (user_id, username) VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    ''', user_id, username)
    await conn.close()

async def clear_favorites(user_id: int):
    """Очистить избранное"""
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('DELETE FROM favorites WHERE user_id = $1', user_id)
    await conn.close()

async def get_filters(user_id: int):
    """Получить настройки фильтров"""
    conn = await asyncpg.connect(DATABASE_URL)
    filters = await conn.fetchrow('SELECT * FROM filters WHERE user_id = $1', user_id)
    await conn.close()
    
    if not filters:
        return {"length": 6, "chars": "только буквы", "chars_type": "letters", "generation": "читаемые сочетания", "words": []}
    
    return dict(filters)

async def update_filters(user_id: int, **kwargs):
    """Обновить настройки фильтров"""
    conn = await asyncpg.connect(DATABASE_URL)
    set_clause = ', '.join([f"{key} = ${i+2}" for i, key in enumerate(kwargs.keys())])
    values = [user_id] + list(kwargs.values())
    await conn.execute(f'''
        INSERT INTO filters (user_id) VALUES ($1)
        ON CONFLICT (user_id) DO UPDATE SET {set_clause}
    ''', *values)
    await conn.close()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# ========== ФУНКЦИЯ БЕЗОПАСНОЙ ОТПРАВКИ ФОТО ==========

async def safe_answer_photo(message: types.Message, photo: str, caption: str, reply_markup=None, parse_mode=ParseMode.HTML):
    try:
        await message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        return True
    except Exception as e:
        logging.warning(f"Не удалось отправить фото {photo}: {e}")
        try:
            await message.answer_photo(
                photo=IMG_FALLBACK,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
            return True
        except:
            await message.answer(
                caption,
                parse_mode=None,
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
        [InlineKeyboardButton(text="Обычный", callback_data="magnet_normal")],
        [InlineKeyboardButton(text="Fast", callback_data="magnet_fast")],
        [InlineKeyboardButton(text="Mythoc", callback_data="magnet_mythoc")],
        [InlineKeyboardButton(text="Назад", callback_data="search")]
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

def referrals_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])

def premium_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
    return keyboard

def support_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Написать в поддержку", callback_data="support_write")],
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
    return keyboard

def favorites_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Очистить избранное", callback_data="clear_favorites")],
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

# ========== ФУНКЦИИ ==========

def get_default_filters():
    return {
        "length": 6,
        "chars": "только буквы",
        "chars_type": "letters",
        "generation": "читаемые сочетания",
        "words": []
    }

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

def generate_username(length: int, chars_type: str = "letters") -> str:
    if chars_type == "letters":
        chars = string.ascii_lowercase
    else:
        chars = string.ascii_lowercase + string.digits
    
    return ''.join(random.choices(chars, k=length))

# ========== ОБРАБОТЧИКИ ==========

@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = int(args[1].replace("ref_", ""))
        if referrer_id != user_id:
            referrer = await get_user(referrer_id)
            if referrer:
                await update_user(referrer_id, invited=referrer['invited'] + 1)
                await update_user(referrer_id, attempts=referrer['attempts'] + 5)
    
    await create_user(user_id, username)
    
    # Проверяем восстановление попыток
    was_reset = await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    if was_reset and user:
        # Отправляем сообщение о восстановлении попыток
        await message.answer(
            "<b>Ваши бесплатные попытки восстановлены!</b>\n\n"
            f"Доступно: {user['attempts']} попыток на сегодня.\n\n"
            "Нажмите Поиск чтобы начать!",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu()
        )
    else:
        await safe_answer_photo(
            message,
            IMG_MENU,
            "<b>Добро пожаловать в Hunter!</b>\n\nВыберите действие:",
            main_menu(),
            ParseMode.HTML
        )

@dp.callback_query(lambda c: c.data == "menu")
async def menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    try:
        await safe_answer_photo(
            callback.message,
            IMG_MENU,
            "<b>Добро пожаловать в Hunter!</b>\n\nВыберите действие:",
            main_menu(),
            ParseMode.HTML
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при возврате в меню")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "search")
async def search_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    if not user or user['attempts'] <= 0:
        await callback.message.answer(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    try:
        await safe_answer_photo(
            callback.message,
            IMG_SEARCH,
            "<b>Поиск</b>\n\nВыберите раздел ниже:",
            search_options_menu(),
            ParseMode.HTML
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе поиска")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "search_filters")
async def search_filters_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    if not user or user['attempts'] <= 0:
        await callback.message.answer(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    try:
        filters = await get_filters(user_id)
        
        text = (
            "<b>Фильтры</b>\n\n"
            "Настройка поиска\n"
            "Текущие параметры:\n"
            f"- Длина: {filters['length']} символов\n"
            f"- Символы: {filters['chars']}\n"
            f"- Генерация: {filters['generation']}\n"
            f"- Слова: {'не добавлены' if not filters['words'] else ', '.join(filters['words'])}\n\n"
            f"Доступно попыток: {user['attempts']}"
        )
        
        await safe_answer_photo(
            callback.message,
            IMG_FILTERS,
            text,
            filters_menu(),
            ParseMode.HTML
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе фильтров")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "filter_length")
async def filter_length_callback(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "<b>Выберите длину</b>\n\n"
            "Выберите длину юзернейма:",
            parse_mode=ParseMode.HTML,
            reply_markup=filter_length_menu()
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
        await callback.message.edit_text(
            "<b>Изменить символы</b>\n\n"
            "Выберите тип символов:",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
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
        await callback.message.edit_text(
            "<b>Изменить тип генерации</b>\n\n"
            "Выберите способ генерации:",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
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
    try:
        await callback.message.edit_text(
            "<b>Добавить слова</b>\n\n"
            "Отправьте список слов через запятую.\n"
            "Например: game, boss, sky, pro\n\n"
            "Бот будет использовать эти слова для генерации.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_to_menu()
        )
    except Exception as e:
        logging.exception("Ошибка при добавлении слов")
    finally:
        await callback.answer()

@dp.message()
async def handle_words_input(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    try:
        if "," in text:
            words = [w.strip().lower() for w in text.split(",") if w.strip()]
        else:
            words = [text.lower()]
        
        await update_filters(user_id, words=words)
        
        await message.answer(
            f"Слова добавлены: {', '.join(words)}",
            parse_mode=ParseMode.HTML,
            reply_markup=back_to_menu()
        )
    except Exception as e:
        logging.exception("Ошибка при обработке слов")

@dp.callback_query(lambda c: c.data == "filter_start")
async def filter_start_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await reset_attempts_if_needed(user_id)
    user = await get_user(user_id)
    
    if not user or user['attempts'] <= 0:
        await callback.message.edit_text(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            parse_mode=ParseMode.HTML,
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
            parse_mode=ParseMode.HTML,
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
            parse_mode=ParseMode.HTML,
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    await show_chars_selection(callback, user_id, 6)

@dp.callback_query(lambda c: c.data == "chars_letters")
async def chars_letters_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    length = user_data.get(user_id, {}).get("pending_length", 5)
    chars_type = "letters"
    chars_name = "только буквы"
    
    await callback.message.delete()
    await do_search_with_animation(callback.message, user_id, length, chars_type, chars_name)

@dp.callback_query(lambda c: c.data == "chars_letters_digits")
async def chars_letters_digits_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    length = user_data.get(user_id, {}).get("pending_length", 5)
    chars_type = "letters_digits"
    chars_name = "буквы и цифры"
    
    await callback.message.delete()
    await do_search_with_animation(callback.message, user_id, length, chars_type, chars_name)

@dp.callback_query(lambda c: c.data == "search_magnet")
async def magnet_callback(callback: CallbackQuery):
    try:
        await safe_answer_photo(
            callback.message,
            IMG_MAGNET,
            "<b>Магнит</b>\n\nВыберите раздел ниже:\n\nМагнит\nОбычный - стандартная скорость.\nFast - быстрая скорость.",
            magnet_menu(),
            ParseMode.HTML
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
    
    if not user or user['attempts'] <= 0:
        await callback.message.answer(
            "<b>Попытки закончились!</b>\n\n"
            "Пригласите друга для получения дополнительных попыток.",
            parse_mode=ParseMode.HTML,
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
    await reset_attempts_if_needed(user_id)
    
    try:
        user = await get_user(user_id)
        if not user:
            await create_user(user_id)
            user = await get_user(user_id)
        
        favorites = await get_favorites(user_id)
        tg_username = user['username'] if user['username'] else "не установлен"
        
        status = "Premium" if user['is_premium'] else "Обычный"
        
        profile_text = (
            f"<b>Ваш профиль</b>\n"
            f"ID: {user_id}\n"
            f"Telegram: @{tg_username}\n"
            f"Статус: {status}\n"
            f"Количество попыток: {user['attempts']}\n"
            f"Приглашено друзей: {user['invited']}\n\n"
            f"Ваш юзернейм: @{user['username'] if user['username'] else 'не найден'}"
        )
        
        await safe_answer_photo(
            callback.message,
            IMG_PROFILE,
            profile_text,
            profile_menu(len(favorites)),
            ParseMode.HTML
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
            fav_list = "\n".join([f"@{name}" for name in favorites])
            text = f"<b>Избранное</b> ({len(favorites)})\n\n{fav_list}"
        else:
            text = "<b>Избранное</b> (0)\n\nУ вас пока нет избранных юзернеймов."
        
        await callback.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=favorites_menu()
        )
    except Exception as e:
        logging.exception("Ошибка при показе избранного")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "info")
async def info_callback(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "<b>Информация</b>\n\n"
            "Hunter - бот для поиска свободных юзернеймов\n\n"
            "Проверка на t.me и fragment.com\n"
            "Оценка качества юзернеймов\n"
            "3 попытки бесплатно каждый день\n"
            "Приглашай друзей и получай бонусы!\n\n"
            "Версия: 1.0",
            parse_mode=ParseMode.HTML,
            reply_markup=back_to_menu()
        )
    except Exception as e:
        logging.exception("Ошибка при показе информации")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "premium")
async def premium_callback(callback: CallbackQuery):
    try:
        await safe_answer_photo(
            callback.message,
            IMG_PREMIUM,
            "<b>Premium</b>\n\nВ разработке\nСкоро здесь будут доступны премиум-функции!",
            back_to_menu(),
            ParseMode.HTML
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе премиум")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "referrals")
async def referrals_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
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
            "2 друга - 2 попытки\n"
            "4 друга - 6 попыток\n"
            "6 друзей - 10 попыток\n"
            "Дальше каждые 2 друга - ещё 4 попытки\n\n"
            f"<b>Ваша реферальная ссылка:</b>\n"
            f"https://t.me/{bot_username}?start=ref_{user_id}"
        )
        
        await safe_answer_photo(
            callback.message,
            IMG_REFERRALS,
            text,
            referrals_menu(),
            ParseMode.HTML
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе рефералов")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "support")
async def support_callback(callback: CallbackQuery):
    try:
        text = (
            f"<b>Поддержка</b>\n\n"
            f"По всем вопросам пишите:\n"
            f"@{SUPPORT_USERNAME}\n\n"
            "Часто задаваемые вопросы:\n"
            "Как получить больше попыток?\n"
            "  - Приглашайте друзей!\n"
            "Почему юзернейм занят?\n"
            "  - Он уже используется в Telegram\n"
            "Как работает оценка?\n"
            "  - Учитывается длина, цифры, символы\n\n"
            f"Попытки восстанавливаются в 00:00 по МСК"
        )
        
        await safe_answer_photo(
            callback.message,
            IMG_SUPPORT,
            text,
            support_menu(),
            ParseMode.HTML
        )
        await callback.message.delete()
    except Exception as e:
        logging.exception("Ошибка при показе поддержки")
    finally:
        await callback.answer()

@dp.callback_query(lambda c: c.data == "support_write")
async def support_write_callback(callback: CallbackQuery):
    await callback.answer(f"Напишите @{SUPPORT_USERNAME}", show_alert=True)

# ========== ОСНОВНЫЕ ФУНКЦИИ ПОИСКА ==========

async def show_chars_selection(callback: CallbackQuery, user_id: int, length: int):
    try:
        # Сохраняем длину в память
        if user_id not in user_data:
            user_data[user_id] = {}
        user_data[user_id]["pending_length"] = length
        
        await callback.message.delete()
        await safe_answer_photo(
            callback.message,
            IMG_SEARCH,
            "<b>Какие символы использовать?</b>\n\n"
            "Выберите один из вариантов - бот учтёт его при поиске свободного юзернейма.",
            chars_menu(),
            ParseMode.HTML
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
        
        # Отправляем новое сообщение с анимацией
        status_msg = await message.answer(
            "<b>Поиск</b>\n\n"
            "Ищу свободный юзернейм для тебя\n"
            "Проверяю сейчас: ...",
            parse_mode=ParseMode.HTML
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
            
            await status_msg.edit_text(
                f"<b>Поиск</b>\n\n"
                "Ищу свободный юзернейм для тебя\n"
                f"Проверяю сейчас: @{username}",
                parse_mode=ParseMode.HTML
            )
            
            result = check_username(username)
            attempts += 1
            
            if result["available"]:
                found_username = username
                break
            
            await asyncio.sleep(0.3)
        
        # Обновляем попытки
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
                search_result_menu(),
                ParseMode.HTML
            )
        else:
            text = (
                f"<b>Юзернейм не найден</b>\n\n"
                f"Свободных юзернеймов не найдено.\n\n"
                f"Длина: {filters.get('length', 6)}\n"
                f"Символы: {filters.get('chars', 'только буквы')}\n"
                f"Осталось попыток: {attempts_left}"
            )
            
            await status_msg.edit_text(
                text,
                parse_mode=ParseMode.HTML,
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
        
        # Отправляем новое сообщение с анимацией
        status_msg = await message.answer(
            "<b>Поиск</b>\n\n"
            "Ищу свободный юзернейм для тебя\n"
            "Проверяю сейчас: ...",
            parse_mode=ParseMode.HTML
        )
        
        found_username = None
        attempts = 0
        max_attempts = 50 if is_premium else 20
        
        while attempts < max_attempts:
            username = generate_username(length, chars_type)
            
            await status_msg.edit_text(
                f"<b>Поиск</b>\n\n"
                "Ищу свободный юзернейм для тебя\n"
                f"Проверяю сейчас: @{username}",
                parse_mode=ParseMode.HTML
            )
            
            result = check_username(username)
            attempts += 1
            
            if result["available"]:
                found_username = username
                break
            
            await asyncio.sleep(0.3)
        
        # Обновляем попытки
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
                search_result_menu(),
                ParseMode.HTML
            )
        else:
            text = (
                f"<b>Юзернейм не найден</b>\n\n"
                f"Свободных юзернеймов не найдено.\n\n"
                f"Длина: {length}\n"
                f"Символы: {chars_name}\n"
                f"Осталось попыток: {attempts_left}"
            )
            
            await status_msg.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=search_result_menu()
            )
    except Exception as e:
        logging.exception("Ошибка при поиске с анимацией")

# ========== ЗАПУСК ==========
async def main():
    await init_db()
    print(f"{BOT_NAME} bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
