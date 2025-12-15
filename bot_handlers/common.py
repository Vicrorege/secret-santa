import telebot
from telebot import types
import string
import random
from db_manager import db_execute, get_user_info, is_fantom

# Контекст для /sudo: {'target': tg_id, 'admin': admin_tg_id}
SUDO_CONTEXT = None

def set_sudo_context(target_tg_id, admin_tg_id):
    global SUDO_CONTEXT
    SUDO_CONTEXT = {'target': target_tg_id, 'admin': admin_tg_id}

def clear_sudo_context():
    global SUDO_CONTEXT
    SUDO_CONTEXT = None

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
        first = user[3] or ''
        last = user[4] or ''
        username = user[2] or ''
        # Prefer first+last, fall back to username, then to ID
        full = (first + (' ' + last if last else '')).strip()
        name = full or username or f"ID: {user[1]}"
    else:
        name = f"ID: {tg_id}"

    # Always return an HTML link (escape display name)
    return f'<a href="tg://user?id={tg_id}">{escape_html(name)}</a>'

def main_menu_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎄 Создать новую игру", callback_data='create_game'))
    markup.add(types.InlineKeyboardButton("🎁 Мои игры", callback_data='my_games'))
    return markup

def check_fantom(bot, chat_id):
    """
    Проверить, не является ли пользователь фантомом.
    Если фантом - отправить сообщение и вернуть True, иначе False.
    """
    if is_fantom(chat_id):
        # Не отправляем никаких сообщений фантомам (чтобы не вызывать ошибок 'chat not found')
        return True
    return False

def send(bot, chat_id, text, reply_markup=None, parse_mode=None):
    """
    Отправить сообщение пользователю с предварительной проверкой роли fantom.
    
    Args:
        bot: Объект бота Telebot
        chat_id (int): ID чата для отправки
        text (str): Текст сообщения
        reply_markup: Разметка клавиатуры (опционально)
        parse_mode (str): Режим парсинга ('HTML', 'Markdown' и т.д.) (опционально)
        
    Returns:
        Message: Объект отправленного сообщения или None если пользователь fantom
    """
    if is_fantom(chat_id):
        # Не пытаться отправлять сообщения фантомам — просто молча пропускаем отправку
        return None

    # Если мы в /sudo контексте и сообщение адресовано цели sudo,
    # перенаправляем текст администратору вместо прямой отправки (чтобы не вызывать "chat not found").
    if SUDO_CONTEXT and chat_id == SUDO_CONTEXT.get('target'):
        admin_id = SUDO_CONTEXT.get('admin')
        try:
            prefixed = f"[to {chat_id}] {text}"
            return bot.send_message(admin_id, prefixed, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            # Если даже отправить администратору не удалось, тихо вернуть None
            return None

    return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

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