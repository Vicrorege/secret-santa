import telebot
from telebot import types
from dotenv import load_dotenv
import os
from db_manager import init_db, get_game_id_by_code, is_admin, get_game_info
import bot_handlers.common as common
import bot_handlers.game_creation as gc
import bot_handlers.game_panels as gp
import bot_handlers.game_actions as ga
import bot_handlers.admin_panel as ap

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN') 

if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения или файле .env")

bot = telebot.TeleBot(TOKEN)
user_states = {}

init_db()

# --- COMMAND HANDLERS ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    common.register_user(message)
    
    payload = message.text.split(' ')[1] if len(message.text.split(' ')) > 1 else None
    
    if payload:
        invite_code = payload 
        game_id = get_game_id_by_code(invite_code) # Импорт из db_manager теперь корректен
        if game_id:
            ga.join_game_prompt(bot, message, game_id)
            return
    
    bot.send_message(
        message.chat.id, 
        "Привет! Я бот для игры в Тайного Санту. Выбери действие:", 
        reply_markup=common.main_menu_markup()
    )

@bot.message_handler(commands=['admin'])
def handle_admin(message):
    if is_admin(message.from_user.id):
        ap.admin_panel(bot, message)
    else:
        bot.send_message(message.chat.id, "У вас нет прав администратора.")

@bot.message_handler(commands=['trigger'])
def handle_trigger(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "У вас нет прав администратора для этой команды.")
        return
        
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.send_message(message.chat.id, "Использование: /trigger <callback_data>")
            return
            
        callback_data = parts[1].strip()
        
        mock_call = types.CallbackQuery(
            id='admin_trigger', 
            from_user=message.from_user, 
            data=callback_data, 
            chat_instance='mock_chat_instance', 
            message=message, 
            json_string='{}'
        )
        
        callback_inline(mock_call)
        
        bot.delete_message(message.chat.id, message.message_id)
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при имитации нажатия: {e}")

@bot.message_handler(commands=['cancel'])
def handle_cancel(message):
    if message.chat.id in user_states:
        del user_states[message.chat.id]
        bot.send_message(message.chat.id, "Действие отменено.", reply_markup=common.main_menu_markup())

# --- MESSAGE HANDLERS (for states) ---
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) and user_states[message.chat.id][0] == 'waiting_game_name')
def handle_game_name(message):
    gc.handle_game_name(bot, message, user_states)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) and user_states[message.chat.id][0] == 'waiting_budget')
def handle_budget(message):
    gc.handle_budget(bot, message, user_states)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) and user_states[message.chat.id][0] == 'waiting_wish_text')
def handle_wish_text(message):
    ga.handle_wish_text(bot, message, user_states)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) and user_states[message.chat.id][0] == 'waiting_admin_edit')
def handle_admin_edit_input(message):
    ap.handle_admin_edit_input(bot, message, user_states)

# --- CALLBACK QUERY HANDLER ---
@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    data = call.data
    tg_id = call.from_user.id
    
    if data.startswith('admin_'):
        ap.callback_admin_panel(bot, call, user_states)
        return

    if data == 'menu':
        bot.edit_message_text(
            "Привет! Я бот для игры в Тайного Санту. Выбери действие:", 
            tg_id, 
            call.message.message_id, 
            reply_markup=common.main_menu_markup()
        )
    elif data == 'create_game':
        bot.delete_message(tg_id, call.message.message_id)
        gc.create_game_start(bot, call.message, user_states)
    elif data == 'my_games':
        gp.my_games_panel(bot, call)
    elif data.startswith('join_'):
        game_id = int(data.split('_')[1])
        ga.join_game_action(bot, call, game_id)
    elif data.startswith('select_currency_'):
        gc.handle_currency_select_callback(bot, call, user_states)
    elif data.startswith('org_panel_'):
        game_id = int(data.split('_')[2])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            gp.organizer_panel(bot, tg_id, game_id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав на управление этой игрой.")
    elif data.startswith('view_game_'):
        game_id = int(data.split('_')[2])
        gp.participant_game_view(bot, call, game_id)
    elif data.startswith('draw_'):
        game_id = int(data.split('_')[-1])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            result_message, success = ga.draw_pairs(bot, game_id, tg_id)
            bot.answer_callback_query(call.id, result_message)
            gp.organizer_panel(bot, tg_id, game_id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав организатора.")
    elif data.startswith('wish_game_'):
        game_id = int(data.split('_')[2])
        ga.prompt_wish_text(bot, call, game_id, user_states)
    elif data.startswith('delete_game_'):
        game_id = int(data.split('_')[2])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            ga.delete_game_confirm(bot, call, game_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав организатора.")
    elif data.startswith('confirm_delete_'):
        game_id = int(data.split('_')[2])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            ga.delete_game_action(bot, call, game_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав организатора.")
    elif data.startswith('finish_game_'):
        game_id = int(data.split('_')[2])
        game = get_game_info(game_id)
        if game and game[3] == tg_id:
            ga.finish_game_action(bot, call, game_id)
        else:
            bot.answer_callback_query(call.id, "У вас нет прав организатора.")
    else:
        bot.answer_callback_query(call.id, "Действие не распознано.")

if __name__ == '__main__':
    user_states.clear() 
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        pass