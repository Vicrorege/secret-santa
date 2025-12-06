import telebot
import sqlite3
import random
import string
from telebot import types
import json
import re
from dotenv import load_dotenv
import os

PAGE_SIZE = 10 

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN') 
DB_NAME = os.getenv('DB_NAME', 'secret_santa.db') 

if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения или файле .env")

bot = telebot.TeleBot(TOKEN)
user_states = {}

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

def get_game_id_by_code(invite_code):
    result = db_execute("SELECT id FROM games WHERE invite_code = ?", (invite_code,), fetch_one=True)
    return result[0] if result else None

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            tg_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            role TEXT DEFAULT 'user'
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            budget REAL,
            organizer_id INTEGER,
            participants_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'setup',
            invite_code TEXT UNIQUE,
            currency TEXT DEFAULT 'RUB'
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wishes (
            id INTEGER PRIMARY KEY,
            user_tg_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            text TEXT,
            UNIQUE(user_tg_id, game_id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pairs (
            id INTEGER PRIMARY KEY,
            santa_tg_id INTEGER NOT NULL,
            recipient_tg_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            is_admin_pair INTEGER DEFAULT 0,
            UNIQUE(santa_tg_id, game_id),
            UNIQUE(recipient_tg_id, game_id)
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

def db_execute(query, params=(), fetch_one=False, fetch_all=False, commit=False):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        if commit:
            conn.commit()
        if fetch_one:
            return cursor.fetchone()
        elif fetch_all:
            return cursor.fetchall()
    finally:
        conn.close()

def get_table_data(table_name, page_num=0):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    count = cursor.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    
    offset = page_num * PAGE_SIZE
    data = cursor.execute(f"SELECT * FROM {table_name} LIMIT {PAGE_SIZE} OFFSET {offset}").fetchall()
    
    conn.close()
    return columns, data, count

def get_single_record(table_name, record_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    
    record = cursor.execute(f"SELECT * FROM {table_name} WHERE {columns[0]} = ?", (record_id,)).fetchone()
    
    conn.close()
    return columns, record

def get_user_info(tg_id):
    return db_execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,), fetch_one=True)

def get_user_name(tg_id):
    user = get_user_info(tg_id)
    if user:
        name = user[3] or user[2] or f"ID: {user[1]}"
        return name
    return f"Неизвестный пользователь ID:{tg_id}"

def get_game_info(game_id):
    return db_execute("SELECT id, name, budget, organizer_id, participants_json, status, invite_code, currency FROM games WHERE id = ?", (game_id,), fetch_one=True)

def is_admin(tg_id):
    user = get_user_info(tg_id)
    return user and user[5] == 'admin'

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

def main_menu_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎄 Создать новую игру", callback_data='create_game'))
    markup.add(types.InlineKeyboardButton("🎁 Мои игры", callback_data='my_games'))
    return markup

@bot.message_handler(commands=['start'])
def handle_start(message):
    register_user(message)
    
    payload = message.text.split(' ')[1] if len(message.text.split(' ')) > 1 else None
    
    if payload:
        invite_code = payload 
        game_id = get_game_id_by_code(invite_code)
        if game_id:
            join_game_prompt(message, game_id)
            return
    
    bot.send_message(
        message.chat.id, 
        "Привет! Я бот для игры в Тайного Санту. Выбери действие:", 
        reply_markup=main_menu_markup()
    )

@bot.message_handler(commands=['admin'])
def handle_admin(message):
    if is_admin(message.from_user.id):
        admin_panel(message)
    else:
        bot.send_message(message.chat.id, "У вас нет прав администратора.")

@bot.message_handler(commands=['cancel'])
def handle_cancel(message):
    if message.chat.id in user_states:
        del user_states[message.chat.id]
        bot.send_message(message.chat.id, "Действие отменено.", reply_markup=main_menu_markup())

def create_game_start(message):
    bot.send_message(message.chat.id, "Введите название для новой игры (например, 'Новогодний обмен 2025'):")
    user_states[message.chat.id] = ('waiting_game_name', {})

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) and user_states[message.chat.id][0] == 'waiting_game_name')
def handle_game_name(message):
    game_name = message.text.strip()
    tg_id = message.chat.id
    
    if db_execute("SELECT id FROM games WHERE name = ?", (game_name,), fetch_one=True):
        bot.send_message(tg_id, "Игра с таким названием уже существует. Придумайте другое:")
        return

    user_states[tg_id] = ('waiting_budget', {'name': game_name})
    bot.send_message(tg_id, f"Название '{game_name}' принято. Теперь введите максимальный бюджет на подарок (например, 1500.00):")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) and user_states[message.chat.id][0] == 'waiting_budget')
def handle_budget(message):
    tg_id = message.chat.id
    context = user_states[tg_id][1]
    
    try:
        budget = float(message.text.replace(',', '.').strip())
        if budget <= 0:
             raise ValueError
    except ValueError:
        bot.send_message(tg_id, "Некорректная сумма. Введите положительное число (например, 500.50):")
        return
        
    context['budget'] = budget
    user_states[tg_id] = ('waiting_currency', context)
    
    prompt_currency_select(tg_id, budget)

def prompt_currency_select(tg_id, budget):
    text = f"Бюджет **{budget}** принят. Выберите валюту:"
    markup = types.InlineKeyboardMarkup()
    
    for code, description in CURRENCIES.items():
        markup.add(types.InlineKeyboardButton(description, callback_data=f'select_currency_{code}'))
        
    bot.send_message(tg_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_currency_'))
def handle_currency_select_callback(call):
    tg_id = call.from_user.id
    if tg_id not in user_states or user_states[tg_id][0] != 'waiting_currency':
        bot.answer_callback_query(call.id, "Истекло время ожидания или неверный контекст.")
        return
        
    currency_code = call.data.split('_')[2]
    context = user_states[tg_id][1]
    
    if currency_code not in CURRENCIES:
         bot.answer_callback_query(call.id, "Неизвестная валюта.")
         return

    context['currency'] = currency_code
    
    while True:
        invite_code = generate_invite_code()
        if not db_execute("SELECT id FROM games WHERE invite_code = ?", (invite_code,), fetch_one=True):
            break

    query = "INSERT INTO games (name, budget, organizer_id, participants_json, invite_code, currency) VALUES (?, ?, ?, ?, ?, ?)"
    db_execute(query, (context['name'], context['budget'], tg_id, json.dumps([tg_id]), invite_code, context['currency']), commit=True)
    
    game_info = db_execute("SELECT id FROM games WHERE name = ?", (context['name'],), fetch_one=True)
    game_id = game_info[0]
    
    del user_states[tg_id]
    
    bot.edit_message_text(
        f"🎉 Игра <b>'{context['name']}'</b> создана с бюджетом <b>{context['budget']} {context['currency']}</b>.",
        tg_id,
        call.message.message_id,
        parse_mode='HTML'
    )
    organizer_panel(tg_id, game_id)
    
    bot.answer_callback_query(call.id)


def organizer_panel(tg_id, game_id, message_id=None):
    game = get_game_info(game_id)
    if not game:
        bot.send_message(tg_id, "Ошибка: Игра не найдена.")
        return
        
    if game[3] != tg_id:
        bot.send_message(tg_id, "У вас нет прав на управление этой игрой.")
        return

    game_name, budget, organizer_id, participants_json, status, invite_code, currency = game[1], game[2], game[3], game[4], game[5], game[6], game[7]
    participants = json.loads(participants_json)
    
    invite_link = f"https://t.me/{bot.get_me().username}?start={invite_code}"
    participants_list = "\n".join([f"- {get_user_name(p_id)}" for p_id in participants])
    
    text = (
        f"👑 <b>Панель Организатора: {game_name}</b>\n\n"
        f"<i>Бюджет:</i> <b>{budget} {currency}</b>\n"
        f"<i>Участников:</i> <b>{len(participants)}</b>\n"
        f"<i>Статус:</i> <b>{status}</b>\n\n"
        f"<b>Участники:</b>\n"
        f"{participants_list}\n\n"
        f"<b>Ссылка для приглашения:</b>\n"
        f"<code>{invite_link}</code>"
    )

    markup = types.InlineKeyboardMarkup()
    
    if len(participants) < 2 and status == 'setup':
         markup.add(types.InlineKeyboardButton("🚫 Нельзя начать (нужно минимум 2)", callback_data='noop'))
    elif status == 'setup':
        markup.add(types.InlineKeyboardButton(f"🎲 Провести жеребьёвку", callback_data=f'draw_{game_id}'))
    elif status == 'running':
        markup.add(types.InlineKeyboardButton("👀 Посмотреть результаты жеребьёвки", callback_data=f'view_pairs_{game_id}'))
        markup.add(types.InlineKeyboardButton("🔄 Пережеребьёвка", callback_data=f'draw_{game_id}'))
        markup.add(types.InlineKeyboardButton("🎁 Завершить игру", callback_data=f'finish_game_{game_id}'))
    
    markup.add(types.InlineKeyboardButton("🗑️ Удалить игру", callback_data=f'delete_game_{game_id}'))
    markup.add(types.InlineKeyboardButton("⬅️ Назад в Мои игры", callback_data='my_games'))
    
    if message_id:
        bot.edit_message_text(text, tg_id, message_id, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(tg_id, text, reply_markup=markup, parse_mode='HTML')

def participant_game_view(call, game_id):
    tg_id = call.from_user.id
    game = get_game_info(game_id)
    
    if not game:
        bot.answer_callback_query(call.id, "Игра не найдена.", show_alert=True)
        return

    game_name, budget, organizer_id, participants_json, status, invite_code, currency = game[1], game[2], game[3], game[4], game[5], game[6], game[7]
    participants = json.loads(participants_json)
    
    if tg_id not in participants:
        bot.answer_callback_query(call.id, "Вы не являетесь участником этой игры.", show_alert=True)
        return
        
    organizer_name = get_user_name(organizer_id)
    text = f"🎁 <b>Информация об игре: {game_name}</b>\n\n"
    text += f"<i>Организатор:</i> {organizer_name}\n"
    text += f"<i>Бюджет:</i> <b>{budget} {currency}</b>\n"
    text += f"<i>Статус:</i> <b>{status}</b>\n"
    
    markup = types.InlineKeyboardMarkup()
    
    if status == 'running':
        pair = db_execute("SELECT recipient_tg_id FROM pairs WHERE santa_tg_id = ? AND game_id = ?", (tg_id, game_id), fetch_one=True)
        
        if pair:
            recipient_id = pair[0]
            recipient_name = get_user_name(recipient_id)
            
            recipient_wishes = db_execute(
                "SELECT text FROM wishes WHERE user_tg_id = ? AND game_id = ?", 
                (recipient_id, game_id), 
                fetch_one=True
            )
            wish_text = recipient_wishes[0] if recipient_wishes else "Пожелания пока не указаны."

            text += "\n--- 🎅 ---\n"
            text += f"Ваш Тайный Подопечный: <b>{recipient_name}</b>\n\n"
            text += f"🎁 <b>Пожелания:</b>\n"
            text += f"<i>{wish_text}</i>"
        else:
             text += "\n--- ⏳ ---\n"
             text += "Жеребьёвка проведена, но ваша пара не найдена (обратитесь к организатору)."
    elif status == 'setup':
        text += "\n--- ⏳ ---\n"
        text += "Жеребьёвка еще не проводилась."
    elif status == 'finished':
        text += "\n--- ✅ ---\n"
        text += "Игра завершена."
        
    markup.add(types.InlineKeyboardButton("✏️ Мои пожелания", callback_data=f'wish_game_{game_id}'))
    markup.add(types.InlineKeyboardButton("⬅️ Назад в Мои игры", callback_data='my_games'))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')


def join_game_prompt(message, game_id):
    tg_id = message.chat.id
    game = get_game_info(game_id)
    
    if not game:
        bot.send_message(tg_id, "Игра не найдена. Возможно, она была удалена.")
        return
        
    game_name, budget, organizer_id, participants_json, status, invite_code, currency = game[1], game[2], game[3], game[4], game[5], game[6], game[7]
    organizer_name = get_user_name(organizer_id)
    participants = json.loads(participants_json)
    
    if tg_id in participants:
        bot.send_message(tg_id, f"Вы уже являетесь участником игры <b>'{game_name}'</b>.", parse_mode='HTML')
        return

    text = (
        f"Вас пригласили в игру Тайного Санты <b>'{game_name}'</b>!\n\n"
        f"<i>Организатор:</i> {organizer_name}\n"
        f"<i>Максимальный бюджет:</i> <b>{budget} {currency}</b>\n"
        f"<i>Участников сейчас:</i> {len(participants)}"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Присоединиться", callback_data=f'join_{game_id}'))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data='menu'))

    bot.send_message(tg_id, text, reply_markup=markup, parse_mode='HTML')

def join_game_action(call, game_id):
    tg_id = call.from_user.id
    game = get_game_info(game_id)
    
    if not game:
        bot.edit_message_text("Ошибка: Игра не найдена.", call.message.chat.id, call.message.message_id)
        return
        
    game_name = game[1]
    participants_json = game[4]
    participants = json.loads(participants_json)
    
    if tg_id not in participants:
        participants.append(tg_id)
        new_participants_json = json.dumps(participants)
        
        db_execute(
            "UPDATE games SET participants_json = ? WHERE id = ?", 
            (new_participants_json, game_id), 
            commit=True
        )
        
        bot.edit_message_text(
            f"Вы успешно присоединились к игре <b>'{game_name}'</b>!", 
            call.message.chat.id, 
            call.message.message_id, 
            parse_mode='HTML',
            reply_markup=main_menu_markup()
        )
        organizer_id = game[3]
        bot.send_message(organizer_id, f"🔔 {get_user_name(tg_id)} присоединился(ась) к игре <b>'{game_name}'</b>.", parse_mode='HTML')
    else:
        bot.answer_callback_query(call.id, "Вы уже в этой игре.")

def draw_pairs(game_id, tg_id):
    game = get_game_info(game_id)
    
    if not game or game[3] != tg_id:
        return "Ошибка: Игра не найдена или вы не организатор.", False
    
    game_name, organizer_id, participants_json, status, invite_code, currency = game[1], game[3], game[4], game[5], game[6], game[7]
    all_participants = json.loads(participants_json)
    
    if len(all_participants) < 2:
        return "Недостаточно участников для жеребьёвки (нужно минимум 2).", False
        
    admin_pairs_tuple = db_execute(
        "SELECT santa_tg_id, recipient_tg_id FROM pairs WHERE game_id = ? AND is_admin_pair = 1", 
        (game_id,), 
        fetch_all=True
    )
    admin_pairs = list(admin_pairs_tuple) if admin_pairs_tuple else []
    
    manual_santas = {santa for santa, recipient in admin_pairs}
    manual_recipients = {recipient for santa, recipient in admin_pairs}
    
    remaining_participants = [p for p in all_participants if p not in manual_santas and p not in manual_recipients]
    
    if not set(all_participants).issuperset(manual_santas.union(manual_recipients)):
         return "Ошибка: Неверно назначены пары. В ручных парах есть участники, не входящие в игру.", False

    remaining_santas = list(remaining_participants)
    remaining_recipients = list(remaining_participants)
    
    if remaining_santas:
        random.shuffle(remaining_recipients)
        
        count = 0
        while any(s == r for s, r in zip(remaining_santas, remaining_recipients)):
            random.shuffle(remaining_recipients)
            count += 1
            if count > 1000:
                 return "Ошибка: Невозможно составить пары для оставшихся участников без конфликтов.", False
                 
        random_pairs = list(zip(remaining_santas, remaining_recipients))
    else:
        random_pairs = []

    final_pairs = admin_pairs + random_pairs
    
    db_execute("DELETE FROM pairs WHERE game_id = ?", (game_id,), commit=True)
    
    try:
        for santa, recipient in final_pairs:
            santa_id, recipient_id = santa, recipient 
            is_admin_pair = 1 if (santa_id, recipient_id) in admin_pairs_tuple else 0
            
            db_execute(
                "INSERT INTO pairs (santa_tg_id, recipient_tg_id, game_id, is_admin_pair) VALUES (?, ?, ?, ?)",
                (santa_id, recipient_id, game_id, is_admin_pair),
                commit=True
            )
        
        db_execute("UPDATE games SET status = 'running' WHERE id = ?", (game_id,), commit=True)
        
        successful_sends = []
        failed_sends = []
        
        for santa, recipient in final_pairs:
            recipient_name = get_user_name(recipient)
            recipient_wishes = db_execute(
                "SELECT text FROM wishes WHERE user_tg_id = ? AND game_id = ?", 
                (recipient, game_id), 
                fetch_one=True
            )
            
            wish_text = recipient_wishes[0] if recipient_wishes else "Пожелания пока не указаны."
            
            message_text = (
                f"🚨 <b>ЖЕРЕБЬЁВКА В ИГРЕ '{game_name}' ЗАВЕРШЕНА!</b> 🚨\n\n"
                f"Ваш Тайный Подопечный: <b>{recipient_name}</b>\n\n"
                f"🎁 <b>Пожелания для подарка:</b>\n"
                f"<i>{wish_text}</i>\n\n"
                f"💰 <i>Максимальный бюджет: {game[2]} {currency}</i>"
            )
            
            try:
                bot.send_message(santa, message_text, parse_mode='HTML')
                successful_sends.append(santa)
            except Exception as e:
                failed_sends.append((santa, e))
                
        return (f"✅ Жеребьёвка успешно проведена!\nРазослано {len(successful_sends)} результатов. \nНе удалось разослать {len(failed_sends)}.", True)

    except sqlite3.IntegrityError:
        return "Ошибка БД: Дубликат в парах. Попробуйте пережеребьёвку.", False

    except Exception as e:
        return f"Неизвестная ошибка при жеребьёвке: {str(e)}", False

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    data = call.data
    tg_id = call.from_user.id
    message_id = call.message.message_id
    
    if data == 'menu':
        bot.edit_message_text(
            "Привет! Я бот для игры в Тайного Санту. Выбери действие:", 
            tg_id, 
            message_id, 
            reply_markup=main_menu_markup()
        )
    elif data == 'create_game':
        bot.delete_message(tg_id, message_id)
        create_game_start(call.message)
    elif data == 'my_games':
        my_games_panel(call)
    elif data.startswith('join_'):
        game_id = int(data.split('_')[1])
        join_game_action(call, game_id)
    elif data.startswith('select_currency_'):
        handle_currency_select_callback(call)
    elif data.startswith('org_panel_'):
        game_id = int(data.split('_')[2])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            organizer_panel(tg_id, game_id, message_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав на управление этой игрой.")
    # НОВАЯ ОБРАБОТКА ДЛЯ УЧАСТНИКА
    elif data.startswith('view_game_'):
        game_id = int(data.split('_')[2])
        participant_game_view(call, game_id)
    # КОНЕЦ НОВОЙ ОБРАБОТКИ
    elif data.startswith('draw_'):
        game_id = int(data.split('_')[-1])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            result_message, success = draw_pairs(game_id, tg_id)
            bot.answer_callback_query(call.id, result_message)
            organizer_panel(tg_id, game_id, message_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав организатора.")
    elif data.startswith('view_pairs_'):
        game_id = int(data.split('_')[2])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            view_pairs_organizer(call, game_id)
        else:
             bot.answer_callback_query(call.id, "У вас нет прав организатора.")
    elif data.startswith('wish_game_'):
        game_id = int(data.split('_')[2])
        prompt_wish_text(call, game_id)
    elif data.startswith('delete_game_'):
        game_id = int(data.split('_')[2])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            delete_game_confirm(call, game_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав организатора.")
    elif data.startswith('confirm_delete_'):
        game_id = int(data.split('_')[2])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            delete_game_action(call, game_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав организатора.")
    elif data.startswith('finish_game_'):
        game_id = int(data.split('_')[2])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            finish_game_action(call, game_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав организатора.")
    elif data.startswith('admin_'):
        callback_admin_panel(call)
    else:
        bot.answer_callback_query(call.id, "Действие не распознано.")

def my_games_panel(call):
    tg_id = call.from_user.id
    message_id = call.message.message_id
    
    org_games = db_execute("SELECT id, name, status FROM games WHERE organizer_id = ?", (tg_id,), fetch_all=True)
    all_games = db_execute("SELECT id, name, participants_json, organizer_id, status, currency FROM games", fetch_all=True)
    
    participant_games = []
    wish_games = []
    
    for game_id, name, participants_json, organizer_id, status, currency in all_games:
        participants = json.loads(participants_json)
        if tg_id in participants:
            if organizer_id != tg_id:
                participant_games.append((game_id, name))
            if status != 'finished':
                 wish_games.append((game_id, name))

    text = "🗓️ <b>Ваши игры Тайного Санты</b>\n"
    markup = types.InlineKeyboardMarkup()
    
    if org_games:
        text += "\n👑 <b>Организатор:</b>\n"
        for game_id, name, status in org_games:
            status_emoji = '⚙️' if status == 'setup' else '🏃'
            markup.add(types.InlineKeyboardButton(f"{status_emoji} {name} (Орг)", callback_data=f'org_panel_{game_id}'))
            
    if participant_games:
        text += "\n👥 <b>Участник (Просмотр):</b>\n"
        for game_id, name in participant_games:
            markup.add(types.InlineKeyboardButton(f"🎁 {name} (Уч.)", callback_data=f'view_game_{game_id}'))
            
    if wish_games:
        text += "\n📝 <b>Написать/изменить пожелание:</b>\n"
        for game_id, name in wish_games:
            markup.add(types.InlineKeyboardButton(f"✏️ {name}", callback_data=f'wish_game_{game_id}'))
            
    if not org_games and not participant_games and not wish_games:
        text += "\nУ вас пока нет активных игр."

    markup.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data='menu'))

    bot.edit_message_text(text, tg_id, message_id, reply_markup=markup, parse_mode='HTML')


def view_pairs_organizer(call, game_id):
    tg_id = call.from_user.id
    game = get_game_info(game_id)
    
    if not game or game[3] != tg_id:
        bot.answer_callback_query(call.id, "У вас нет прав для просмотра.")
        return
        
    game_name = game[1]
    pairs = db_execute("SELECT santa_tg_id, recipient_tg_id, is_admin_pair FROM pairs WHERE game_id = ?", (game_id,), fetch_all=True)
    
    if not pairs:
        bot.answer_callback_query(call.id, "Жеребьёвка ещё не проводилась.")
        return
        
    text = f"👀 <b>Результаты жеребьёвки: {game_name}</b>\n\n"
    
    for santa_id, recipient_id, is_admin_pair in pairs:
        santa_name = get_user_name(santa_id)
        recipient_name = get_user_name(recipient_id)
        source = " (Руч.)" if is_admin_pair else ""
        text += f"<b>{santa_name}</b> ➡️ <b>{recipient_name}</b>{source}\n"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад в Настройки", callback_data=f'org_panel_{game_id}'))
    
    bot.edit_message_text(text, tg_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    
def finish_game_action(call, game_id):
    tg_id = call.from_user.id
    game = get_game_info(game_id)
    
    if not game or game[3] != tg_id:
        bot.answer_callback_query(call.id, "У вас нет прав.")
        return
        
    db_execute("UPDATE games SET status = 'finished' WHERE id = ?", (game_id,), commit=True)
    bot.answer_callback_query(call.id, f"Игра '{game[1]}' завершена!")
    organizer_panel(tg_id, game_id, call.message.message_id)

def delete_game_confirm(call, game_id):
    game = get_game_info(game_id)
    
    if not game or game[3] != call.from_user.id:
        bot.answer_callback_query(call.id, "У вас нет прав.")
        return
        
    text = f"⚠️ <b>Внимание!</b> Вы уверены, что хотите <b>безвозвратно</b> удалить игру <b>'{game[1]}'</b>?"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ ДА, удалить", callback_data=f'confirm_delete_{game_id}'))
    markup.add(types.InlineKeyboardButton("❌ НЕТ, отмена", callback_data=f'org_panel_{game_id}'))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

def delete_game_action(call, game_id):
    tg_id = call.from_user.id
    game = get_game_info(game_id)
    
    if not game or game[3] != tg_id:
        bot.answer_callback_query(call.id, "У вас нет прав.")
        return
        
    db_execute("DELETE FROM pairs WHERE game_id = ?", (game_id,), commit=True)
    db_execute("DELETE FROM wishes WHERE game_id = ?", (game_id,), commit=True)
    db_execute("DELETE FROM games WHERE id = ?", (game_id,), commit=True)
    
    bot.edit_message_text(f"🗑️ Игра <b>'{game[1]}'</b> и все связанные данные удалены.", tg_id, call.message.message_id, parse_mode='HTML')

def prompt_wish_text(call, game_id):
    tg_id = call.from_user.id
    game = get_game_info(game_id)
    
    participants = json.loads(game[4]) if game else []
    if tg_id not in participants:
         bot.answer_callback_query(call.id, "Вы не участвуете в этой игре.")
         return

    current_wish = db_execute(
        "SELECT text FROM wishes WHERE user_tg_id = ? AND game_id = ?", 
        (tg_id, game_id), 
        fetch_one=True
    )
    
    wish_text = current_wish[0] if current_wish else "пока не указаны"
    
    text = (
        f"🎁 <b>Игра: {game[1]}</b>\n\n"
        f"Ваши текущие пожелания:\n"
        f"<i>{wish_text}</i>\n\n"
        f"<b>Введите новые пожелания</b> (это полностью заменит старые). Нажмите /cancel для отмены."
    )
    
    bot.edit_message_text(text, tg_id, call.message.message_id, parse_mode='HTML')
    user_states[tg_id] = ('waiting_wish_text', {'game_id': game_id})
    
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) and user_states[message.chat.id][0] == 'waiting_wish_text')
def handle_wish_text(message):
    tg_id = message.chat.id
    context = user_states[tg_id][1]
    game_id = context['game_id']
    wish_text = message.text.strip()
    
    query = """
        INSERT OR REPLACE INTO wishes (user_tg_id, game_id, text) 
        VALUES (?, ?, ?)
    """
    db_execute(query, (tg_id, game_id, wish_text), commit=True)
    
    del user_states[tg_id]
    
    game = get_game_info(game_id)
    bot.send_message(
        tg_id, 
        f"✅ Ваши пожелания для игры <b>'{game[1]}'</b> сохранены.", 
        parse_mode='HTML', 
        reply_markup=main_menu_markup()
    )

def admin_panel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📦 Просмотр БД", callback_data='admin_view_db'))
    markup.add(types.InlineKeyboardButton("🎲 Назначить пары (Setup)", callback_data='admin_tweak_pairs'))
    markup.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data='menu'))

    bot.send_message(message.chat.id, "👑 <b>Панель Администратора</b>", reply_markup=markup, parse_mode='HTML')

def get_db_pages_markup(table_name, current_page, total_count):
    markup = types.InlineKeyboardMarkup()
    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
    
    if total_pages > 1:
        row = []
        if current_page > 0:
            row.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'admin_db_page_{table_name}_{current_page - 1}'))
        
        row.append(types.InlineKeyboardButton(f"Стр. {current_page + 1}/{total_pages}", callback_data='noop'))
        
        if current_page < total_pages - 1:
            row.append(types.InlineKeyboardButton("Вперед ➡️", callback_data=f'admin_db_page_{table_name}_{current_page + 1}'))
        
        markup.add(row)
        
    markup.add(types.InlineKeyboardButton("❌ Закрыть / Назад в таблицы", callback_data='admin_view_db'))
    return markup

def admin_view_db_tables(call):
    if not is_admin(call.from_user.id): return
    
    tables = db_execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'", fetch_all=True)
    
    text = "📂 <b>Выберите таблицу для просмотра/изменения:</b>"
    markup = types.InlineKeyboardMarkup()
    
    for table in tables:
        markup.add(types.InlineKeyboardButton(table[0], callback_data=f'admin_db_table_{table[0]}_0'))
        
    markup.add(types.InlineKeyboardButton("⬅️ Назад в Админ-панель", callback_data='admin_menu'))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

def admin_view_table_data(call, table_name, page):
    if not is_admin(call.from_user.id): return
    
    columns, data, total_count = get_table_data(table_name, page)
    
    text = f"📋 <b>Таблица: {table_name}</b> (Всего записей: {total_count})\n"
    
    main_markup = types.InlineKeyboardMarkup()
    
    if data:
        text += "\nВыберите запись для <b>изменения</b>:"
        
        for row in data:
            record_id = row[0] 
            
            desc_parts = []
            for i, col_name in enumerate(columns):
                if i < 4: 
                    value = str(row[i])
                    if len(value) > 15:
                         value = value[:15] + '...'
                    
                    desc_parts.append(f"{col_name}: {value}")

            button_text = ' | '.join(desc_parts)
            
            main_markup.add(
                types.InlineKeyboardButton(
                    button_text, 
                    callback_data=f'admin_edit_record_{table_name}_{record_id}'
                )
            )
            
    else:
        text += "\nНет данных в этой таблице."
        
    pagination_markup = get_db_pages_markup(table_name, page, total_count)
    
    final_markup = types.InlineKeyboardMarkup(main_markup.keyboard + pagination_markup.keyboard)
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=final_markup, parse_mode='HTML')
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка отображения: {e}")
        admin_view_db_tables(call)


def admin_edit_record_view(call, table_name, record_id):
    if not is_admin(call.from_user.id): return
    
    columns, record = get_single_record(table_name, record_id)
    if not record:
        bot.answer_callback_query(call.id, "Запись не найдена.")
        admin_view_db_tables(call)
        return
        
    text = f"📝 <b>Редактирование записи в {table_name}</b> (ID: {record[0]})\n\n"
    
    edit_markup = types.InlineKeyboardMarkup()
    
    for i, (col_name, value) in enumerate(zip(columns, record)):
        escaped_value = escape_html(value)
        text += f"<b>{col_name}:</b> <code>{escaped_value}</code>\n" 
        
        if i > 0:
            edit_markup.add(
                types.InlineKeyboardButton(
                    f"✏️ Изменить поле {col_name}", 
                    callback_data=f'admin_prompt_edit_{table_name}_{record[0]}_{col_name}'
                )
            )

    edit_markup.add(types.InlineKeyboardButton("⬅️ Назад к таблице", callback_data=f'admin_db_table_{table_name}_0'))
    
    if call.message and call.message.message_id:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=edit_markup, parse_mode='HTML')
    else:
        bot.send_message(call.message.chat.id, text, reply_markup=edit_markup, parse_mode='HTML')


def admin_prompt_edit_value(call, table_name, record_id, col_name):
    if not is_admin(call.from_user.id): return
    
    text = (
        f"✍️ <b>Изменение: {col_name}</b>\n"
        f"Таблица: <b>{table_name}</b>, ID записи: <b>{record_id}</b>\n\n"
        f"Пришлите новое значение для поля <b>'{col_name}'</b>. "
        f"Нажмите /cancel, чтобы отменить."
    )
    
    user_states[call.from_user.id] = ('waiting_admin_edit', {
        'table_name': table_name,
        'record_id': record_id,
        'col_name': col_name,
        'message_to_edit_id': call.message.message_id 
    })
    
    bot.send_message(call.message.chat.id, text, parse_mode='HTML')
    bot.answer_callback_query(call.id)
    

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) and user_states[message.chat.id][0] == 'waiting_admin_edit')
def handle_admin_edit_input(message):
    tg_id = message.chat.id
    
    if tg_id not in user_states or user_states[tg_id][0] != 'waiting_admin_edit':
        return 
        
    context = user_states[tg_id][1]
    
    table_name = context['table_name']
    record_id = context['record_id']
    col_name = context['col_name']
    new_value = message.text.strip()
    
    columns = db_execute(f"PRAGMA table_info({table_name})", fetch_all=True)
    pk_name = columns[0][1] 
    
    query = f"UPDATE {table_name} SET {col_name} = ? WHERE {pk_name} = ?"
    
    try:
        db_execute(query, (new_value, record_id), commit=True)
        
        del user_states[tg_id]
        
        bot.send_message(
            tg_id, 
            f"✅ Поле <b>'{col_name}'</b> в таблице <b>{table_name}</b> (ID: {record_id}) успешно обновлено.", 
            parse_mode='HTML'
        )
        
        mock_message = types.Message(
            message_id=context['message_to_edit_id'], 
            chat=message.chat, 
            date=message.date, 
            from_user=message.from_user, 
            content_type='text', 
            options=[], 
            json_string='{}'
        )
        
        mock_call = types.CallbackQuery(
            id='mock_id', 
            from_user=message.from_user, 
            data=f'admin_edit_record_{table_name}_{record_id}', 
            chat_instance='mock_chat_instance', 
            message=mock_message,
            json_string='{}'
        )
        
        try:
            admin_edit_record_view(mock_call, table_name, record_id)
        except Exception:
            mock_call.message.message_id = None 
            admin_edit_record_view(mock_call, table_name, record_id)
            
    except Exception as e:
        bot.send_message(
            tg_id, 
            f"❌ Ошибка при обновлении поля: {str(e)}", 
            parse_mode='HTML'
        )

def get_admin_game_select_markup(callback_prefix):
    games = db_execute("SELECT id, name FROM games WHERE status = 'setup'", fetch_all=True)
    markup = types.InlineKeyboardMarkup()
    
    if not games:
        markup.add(types.InlineKeyboardButton("Нет игр в статусе 'Setup' для назначения пар", callback_data='noop'))
    else:
        for game_id, name in games:
            markup.add(types.InlineKeyboardButton(name, callback_data=f'{callback_prefix}_{game_id}'))
            
    markup.add(types.InlineKeyboardButton("⬅️ Назад в Админ-панель", callback_data='admin_menu'))
    return markup

def admin_tweak_pairs_select_game(call):
    if not is_admin(call.from_user.id): return
    markup = get_admin_game_select_markup('admin_tweak_game')
    bot.edit_message_text("Выберите игру для назначения пар (статус 'setup'):", call.message.chat.id, call.message.message_id, reply_markup=markup)

def admin_tweak_pairs_show(call, game_id):
    if not is_admin(call.from_user.id): return
    game = get_game_info(game_id)
    if not game: return
    
    admin_pairs = db_execute("SELECT santa_tg_id, recipient_tg_id FROM pairs WHERE game_id = ? AND is_admin_pair = 1", (game_id,), fetch_all=True)
    participants_json = game[4]
    participants = json.loads(participants_json)
    
    text = f"<b>Ручное назначение пар в игре: {game[1]}</b>\n"
    
    if admin_pairs:
        text += "\n<b>Текущие назначенные пары:</b>\n"
        for santa_id, recipient_id, in admin_pairs:
            text += f"<b>{get_user_name(santa_id)}</b> ➡️ <b>{get_user_name(recipient_id)}</b>\n"
    else:
        text += "\nПока нет вручную назначенных пар.\n"

    text += "\nВыберите участника, для которого нужно назначить получателя:"
    
    markup = types.InlineKeyboardMarkup()
    
    for participant_id in participants:
        button_text = f"Санта: {get_user_name(participant_id)}"
        
        markup.add(
            types.InlineKeyboardButton(
                button_text, 
                callback_data=f'admin_assign_recipient_start_{game_id}_{participant_id}'
            )
        )
        
    markup.add(types.InlineKeyboardButton("❌ Удалить все ручные пары", callback_data=f'admin_delete_manual_pairs_{game_id}'))
    markup.add(types.InlineKeyboardButton("⬅️ Назад к выбору игр", callback_data=f'admin_tweak_pairs'))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

def admin_assign_recipient_start(call, game_id, santa_id):
    if not is_admin(call.from_user.id): return
    game = get_game_info(game_id)
    participants = json.loads(game[4])

    text = f"<b>Назначение получателя для {get_user_name(santa_id)}</b>\n\nВыберите получателя:"
    markup = types.InlineKeyboardMarkup()
    
    available_recipients = [p for p in participants if p != santa_id]
    
    for recipient_id in available_recipients:
        markup.add(
            types.InlineKeyboardButton(
                get_user_name(recipient_id), 
                callback_data=f'admin_assign_recipient_execute_{game_id}_{santa_id}_{recipient_id}'
            )
        )
        
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f'admin_tweak_game_{game_id}'))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    
def admin_assign_recipient_execute(call, game_id, santa_id, recipient_id):
    if not is_admin(call.from_user.id): return

    db_execute(
        "DELETE FROM pairs WHERE game_id = ? AND (santa_tg_id = ? OR recipient_tg_id = ?)", 
        (game_id, santa_id, recipient_id), 
        commit=True
    )

    db_execute(
        "INSERT OR REPLACE INTO pairs (santa_tg_id, recipient_tg_id, game_id, is_admin_pair) VALUES (?, ?, ?, 1)",
        (santa_id, recipient_id, game_id), 
        commit=True
    )
    
    bot.answer_callback_query(call.id, f"✅ Пара {get_user_name(santa_id)} ➡️ {get_user_name(recipient_id)} назначена вручную!")
    admin_tweak_pairs_show(call, game_id)
    
def admin_delete_manual_pairs_action(call, game_id):
    if not is_admin(call.from_user.id): return
    
    db_execute("DELETE FROM pairs WHERE game_id = ? AND is_admin_pair = 1", (game_id,), commit=True)
    
    bot.answer_callback_query(call.id, "❌ Все ручные пары удалены!")
    admin_tweak_pairs_show(call, game_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def callback_admin_panel(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "У вас нет прав администратора.", show_alert=True)
        return
        
    data = call.data
    
    if data == 'admin_menu':
        admin_panel(call.message)
    elif data == 'admin_tweak_pairs':
        admin_tweak_pairs_select_game(call)
    elif data.startswith('admin_tweak_game_'):
        parts = data.split('_')
        game_id = int(parts[3])
        admin_tweak_pairs_show(call, game_id)
    elif data.startswith('admin_assign_recipient_start_'):
        parts = data.split('_')
        game_id, santa_id = int(parts[4]), int(parts[5])
        admin_assign_recipient_start(call, game_id, santa_id)
    elif data.startswith('admin_assign_recipient_execute_'):
        parts = data.split('_')
        game_id, santa_id, recipient_id = int(parts[4]), int(parts[5]), int(parts[6])
        admin_assign_recipient_execute(call, game_id, santa_id, recipient_id)
    elif data.startswith('admin_delete_manual_pairs_'):
        game_id = int(data.split('_')[4])
        admin_delete_manual_pairs_action(call, game_id)
    elif data == 'admin_view_db':
        admin_view_db_tables(call)
    elif data.startswith('admin_db_table_'):
        parts = data.split('_')
        table_name = parts[3]
        page = int(parts[4])
        admin_view_table_data(call, table_name, page)
    elif data.startswith('admin_db_page_'):
        parts = data.split('_')
        table_name = parts[3]
        page = int(parts[4])
        admin_view_table_data(call, table_name, page)
    elif data.startswith('admin_prompt_edit_'):
        parts = data.split('_')
        table_name = parts[3]
        record_id = int(parts[4])
        col_name = '_'.join(parts[5:]) 
        admin_prompt_edit_value(call, table_name, record_id, col_name)
    elif data.startswith('admin_edit_record_'): 
        parts = data.split('_')
        table_name = parts[3]
        record_id = int(parts[4])
        admin_edit_record_view(call, table_name, record_id)
    else:
        bot.answer_callback_query(call.id, f"Действие '{data}' пока не реализовано.")

if __name__ == '__main__':
    print("Бот запущен...")
    user_states.clear() 
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Ошибка бота: {e}")