import telebot
from telebot import types
import string
import random
from db_manager import db_execute, get_user_info

CURRENCIES = {
    'RUB': '₽ (Российский рубль)',
    'USD': '$ (Доллар США)',
    'EUR': '€ (Евро)',
    'KZT': '₸ (Казахстанский тенге)'
}

def escape_html(text):
    if text is None:
        return 'NULL'
    text = str(text)
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def generate_invite_code(length=8):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for i in range(length))

def get_user_name(tg_id):
    user = get_user_info(tg_id)
    if user:
        name = user[3] or user[2] or f"ID: {user[1]}"
        return name
    return f"Неизвестный пользователь ID:{tg_id}"

def get_user_link(tg_id):
    user = get_user_info(tg_id)
    if user:
        fulname = user[3]
        fulname +=" " + user[4] if user[4] is not None else ""
        name = fulname or f"ID: {user[1]}"
        return f'<a href="tg://user?id={tg_id}">{name}</a>'
    return f"Неизвестный пользователь ID:{tg_id}"

def main_menu_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎄 Создать новую игру", callback_data='create_game'))
    markup.add(types.InlineKeyboardButton("🎁 Мои игры", callback_data='my_games'))
    return markup

def register_user(message):
    tg_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    if not get_user_info(tg_id):
        query = """
            INSERT INTO users (tg_id, username, first_name, last_name, role) 
            VALUES (?, ?, ?, ?, ?)
        """
        db_execute(query, (tg_id, username, first_name, last_name, 'user'), commit=True)
        return True
    return False