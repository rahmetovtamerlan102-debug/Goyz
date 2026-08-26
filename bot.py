import logging
import time
import asyncio
import requests
import random
import string
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ParseMode

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_NAME = "Hunter"

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

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# ========== ХРАНИЛИЩЕ ДАННЫХ ==========
user_data = {}

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
        [InlineKeyboardButton(text="5 символов", callback_data="search_5")],
        [InlineKeyboardButton(text="6 символов", callback_data="search_6")],
        [InlineKeyboardButton(text="Фильтры", callback_data="search_filters")],
        [InlineKeyboardButton(text="Магнит", callback_data="search_magnet")],
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="За приглашённых друзей", callback_data="referral_friends")],
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
    return keyboard

def premium_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подписка Premium", callback_data="premium_subscribe")],
        [InlineKeyboardButton(text="Что входит?", callback_data="premium_info")],
        [InlineKeyboardButton(text="Купить Premium", callback_data="buy_premium")],
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

# ========== ФУНКЦИИ ==========

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
    
    time.sleep(0.5)
    
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

def get_default_filters():
    return {
        "length": 6,
        "chars": "только буквы",
        "chars_type": "letters",
        "generation": "читаемые сочетания",
        "words": []
    }

# ========== ОБРАБОТЧИКИ ==========

@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = int(args[1].replace("ref_", ""))
        if referrer_id != user_id and referrer_id in user_data:
            user_data[referrer_id]["invited"] += 1
            user_data[referrer_id]["attempts"] += 5
    
    if user_id not in user_data:
        user_data[user_id] = {
            "attempts": 5,
            "invited": 0,
            "favorites": [],
            "username": None,
            "filters": get_default_filters(),
            "last_search": None
        }
    
    await message.answer_photo(
        photo=IMG_MENU,
        caption="*Добро пожаловать в Hunter!*\n\nВыберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu()
    )

@dp.callback_query(lambda c: c.data == "menu")
async def menu_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=IMG_MENU,
        caption="*Добро пожаловать в Hunter!*\n\nВыберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "search")
async def search_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=IMG_SEARCH,
        caption="ПОИСК\n\nВыберите раздел ниже:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=search_options_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "search_5")
async def search_5_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await show_chars_selection(callback, user_id, 5)

@dp.callback_query(lambda c: c.data == "search_6")
async def search_6_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    await show_chars_selection(callback, user_id, 6)

@dp.callback_query(lambda c: c.data == "chars_letters")
async def chars_letters_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    length = user_data[user_id]["pending_length"]
    chars_type = "letters"
    chars_name = "только буквы"
    
    await do_search(callback.message, user_id, length, chars_type, chars_name)

@dp.callback_query(lambda c: c.data == "chars_letters_digits")
async def chars_letters_digits_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    length = user_data[user_id]["pending_length"]
    chars_type = "letters_digits"
    chars_name = "буквы и цифры"
    
    await do_search(callback.message, user_id, length, chars_type, chars_name)

@dp.callback_query(lambda c: c.data == "search_filters")
async def filters_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=IMG_FILTERS,
        caption="ФИЛЬТРЫ\n\nРаздел в разработке\nСкоро здесь появятся настройки фильтров",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_to_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "search_magnet")
async def magnet_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=IMG_MAGNET,
        caption="MAGNIT\n\nВыберите раздел ниже:\n\nМагнит\nОбычный - стандартная скорость.\nFast - быстрая скорость.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=magnet_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("magnet_"))
async def magnet_action_callback(callback: CallbackQuery):
    mode = callback.data.replace("magnet_", "")
    
    mode_names = {
        "normal": "Обычный",
        "fast": "Fast",
        "mythoc": "Mythoc"
    }
    mode_name = mode_names.get(mode, mode)
    
    await callback.message.edit_text(
        f"MAGNIT\n\n{mode_name}\n\n{mode_name} - выбранный режим.\nПоиск запущен...",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_to_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "favorite")
async def favorite_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = user_data.get(user_id, {}).get("username")
    
    if username and username not in user_data[user_id]["favorites"]:
        user_data[user_id]["favorites"].append(username)
        await callback.answer(f"@{username} добавлен в избранное!", show_alert=True)
    else:
        await callback.answer("Нет юзернейма для добавления", show_alert=True)

@dp.callback_query(lambda c: c.data == "clear_favorites")
async def clear_favorites_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data[user_id]["favorites"] = []
    await callback.answer("Избранное очищено!", show_alert=True)
    await profile_callback(callback)

@dp.callback_query(lambda c: c.data == "profile")
async def profile_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {
            "attempts": 5,
            "invited": 0,
            "favorites": [],
            "username": None,
            "filters": get_default_filters()
        }
    
    data = user_data[user_id]
    user = await bot.get_chat(user_id)
    tg_username = user.username if user.username else "не установлен"
    
    profile_text = (
        "ПРОФИЛЬ\n\n"
        f"Ваш профиль\n"
        f"ID: {user_id}\n"
        f"Telegram: @{tg_username}\n"
        f"Статус: Обычный\n"
        f"Количество попыток: {data['attempts']}\n"
        f"Приглашено друзей: {data['invited']}\n\n"
        f"Ваш юзернейм: @{data['username'] if data['username'] else 'не найден'}"
    )
    
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=IMG_PROFILE,
        caption=profile_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=profile_menu(len(data['favorites']))
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "favorites_list")
async def favorites_list_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    favorites = user_data.get(user_id, {}).get("favorites", [])
    
    if favorites:
        fav_list = "\n".join([f"@{name}" for name in favorites])
        text = f"ИЗБРАННОЕ ({len(favorites)})\n\n{fav_list}"
    else:
        text = "ИЗБРАННОЕ (0)\n\nУ вас пока нет избранных юзернеймов."
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=favorites_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "info")
async def info_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "ИНФОРМАЦИЯ\n\n"
        "Hunter - бот для поиска свободных юзернеймов\n\n"
        "Проверка на t.me и fragment.com\n"
        "Оценка качества юзернеймов\n"
        "5 попыток бесплатно\n"
        "Приглашай друзей и получай бонусы!\n\n"
        "Версия: 1.0",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_to_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "premium")
async def premium_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=IMG_PREMIUM,
        caption="PREMIUM\n\nВыберите раздел ниже:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=premium_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "premium_subscribe")
async def premium_subscribe_callback(callback: CallbackQuery):
    await callback.answer("Подписка Premium - 500 руб/мес", show_alert=True)

@dp.callback_query(lambda c: c.data == "premium_info")
async def premium_info_callback(callback: CallbackQuery):
    await callback.answer(
        "Что входит в Premium:\n"
        "Неограниченные попытки\n"
        "Приоритетная проверка\n"
        "Доступ к магниту\n"
        "Персональная поддержка",
        show_alert=True
    )

@dp.callback_query(lambda c: c.data == "buy_premium")
async def buy_premium_callback(callback: CallbackQuery):
    await callback.answer("Оплата через бота - скоро!", show_alert=True)

@dp.callback_query(lambda c: c.data == "referrals")
async def referrals_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    bot_username = (await bot.get_me()).username
    invited = user_data.get(user_id, {}).get("invited", 0)
    
    text = (
        "РЕФЕРАЛЬНАЯ СИСТЕМА\n\n"
        "РЕФЕРАЛЫ\n"
        f"Приглашено друзей: {invited}\n\n"
        "2 друга - 2 попытки\n"
        "4 друга - 6 попыток\n"
        "6 друзей - 10 попыток\n"
        "Дальше каждые 2 друга - ещё 4 попытки\n\n"
        "Ваша реферальная ссылка:\n"
        f"https://t.me/{bot_username}?start=ref_{user_id}"
    )
    
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=IMG_REFERRALS,
        caption=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=referrals_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "referral_friends")
async def referral_friends_callback(callback: CallbackQuery):
    await callback.answer("За приглашённых друзей", show_alert=True)

@dp.callback_query(lambda c: c.data == "support")
async def support_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=IMG_SUPPORT,
        caption="ПОДДЕРЖКА\n\n"
        "По всем вопросам пишите:\n"
        "@your_support\n\n"
        "Часто задаваемые вопросы:\n"
        "Как получить больше попыток?\n"
        "  - Приглашайте друзей!\n"
        "Почему юзернейм занят?\n"
        "  - Он уже используется в Telegram\n"
        "Как работает оценка?\n"
        "  - Учитывается длина, цифры, символы",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=support_menu()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "support_write")
async def support_write_callback(callback: CallbackQuery):
    await callback.answer("Напишите @your_support", show_alert=True)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

async def show_chars_selection(callback: CallbackQuery, user_id: int, length: int):
    if user_id not in user_data:
        user_data[user_id] = {
            "attempts": 5,
            "invited": 0,
            "favorites": [],
            "username": None,
            "filters": get_default_filters()
        }
    
    if user_data[user_id]["attempts"] <= 0:
        await callback.message.delete()
        await callback.message.answer(
            "Попытки закончились!\nПригласите друга для получения дополнительных попыток.",
            reply_markup=back_to_menu()
        )
        await callback.answer()
        return
    
    user_data[user_id]["pending_length"] = length
    
    await callback.message.delete()
    await callback.message.answer(
        "ПОИСК\n\nВыберите раздел ниже:\n\nКакие символы использовать?\nВыберите один из вариантов - бот учтёт его при поиске свободного юзернейма.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=chars_menu()
    )
    await callback.answer()

async def do_search(message: types.Message, user_id: int, length: int, chars_type: str, chars_name: str):
    if user_id not in user_data:
        user_data[user_id] = {
            "attempts": 5,
            "invited": 0,
            "favorites": [],
            "username": None,
            "filters": get_default_filters()
        }

    if user_data[user_id]["attempts"] <= 0:
        await message.edit_text(
            "Попытки закончились!\nПригласите друга для получения дополнительных попыток.",
            reply_markup=back_to_menu()
        )
        return

    status_msg = await message.edit_text(
        f"Поиск {length}-символьных юзернеймов\n"
        f"Символы: {chars_name}\n"
        "Пожалуйста, подождите..."
    )

    found_username = None
    attempts = 0

    while attempts < 20:
        username = generate_username(length, chars_type)
        result = check_username(username)
        attempts += 1
        if result["available"]:
            found_username = username
            break

    user_data[user_id]["attempts"] -= 1
    if user_data[user_id]["attempts"] < 0:
        user_data[user_id]["attempts"] = 0

    attempts_left = user_data[user_id]["attempts"]

    if found_username:
        user_data[user_id]["username"] = found_username
        score, quality, read = get_quality_score(found_username)
        has_digits = "с цифрами" if any(c.isdigit() for c in found_username) else "без цифр"

        # ======== ТОЛЬКО ОЦЕНКА В ЦИТАТЕ ========
        text = (
            "НАЙДЕН\n\n"
            "ЮЗЕРНЕЙМ НАЙДЕН\n"
            f"- Юзернейм: @{found_username}\n"
            '<blockquote expandable="">'
            f"  Качество: {score}/10 - {quality}\n"
            f"  Читаемость: {read} · {has_digits} · длина: {length}\n"
            f"  Статус: свободный"
            "</blockquote>\n\n"
            f"- Осталось попыток: {attempts_left}"
        )

        await status_msg.delete()
        await message.answer_photo(
            photo=IMG_RESULT,
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=search_result_menu()
        )

    else:
        text = (
            "НАЙДЕН\n\n"
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

# ========== ЗАПУСК ==========
async def main():
    print(f"{BOT_NAME} bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
