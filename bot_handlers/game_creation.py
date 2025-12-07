import json
from telebot import types
from db_manager import db_execute, get_game_info
from bot_handlers.common import CURRENCIES, generate_invite_code
from bot_handlers.game_panels import organizer_panel # Импорт панели организатора

def create_game_start(bot, message, user_states):
    bot.send_message(message.chat.id, "Введите название для новой игры (например, 'Новогодний обмен 2025'):")
    user_states[message.chat.id] = ('waiting_game_name', {})

def handle_game_name(bot, message, user_states):
    game_name = message.text.strip()
    tg_id = message.chat.id
    
    if db_execute("SELECT id FROM games WHERE name = ?", (game_name,), fetch_one=True):
        bot.send_message(tg_id, "Игра с таким названием уже существует. Придумайте другое:")
        return

    user_states[tg_id] = ('waiting_budget', {'name': game_name})
    bot.send_message(tg_id, f"Название '{game_name}' принято. Теперь введите максимальный бюджет на подарок (например, 1500.00):")

def prompt_currency_select(bot, tg_id, budget):
    text = f"Бюджет **{budget}** принят. Выберите валюту:"
    markup = types.InlineKeyboardMarkup()
    
    for code, description in CURRENCIES.items():
        markup.add(types.InlineKeyboardButton(description, callback_data=f'select_currency_{code}'))
        
    bot.send_message(tg_id, text, reply_markup=markup, parse_mode='Markdown')

def handle_budget(bot, message, user_states):
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
    
    prompt_currency_select(bot, tg_id, budget)

def handle_currency_select_callback(bot, call, user_states):
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
    organizer_panel(bot, tg_id, game_id)
    
    bot.answer_callback_query(call.id)