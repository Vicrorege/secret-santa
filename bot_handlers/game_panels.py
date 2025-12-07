import json
from telebot import types
from db_manager import db_execute, get_game_info
from bot_handlers.common import get_user_link, main_menu_markup

# Функция для вызова из других модулей, чтобы избежать циклической зависимости
def organizer_panel(bot, tg_id, game_id, message_id=None):
    game = get_game_info(game_id)
    if not game:
        if message_id:
             bot.edit_message_text("Ошибка: Игра не найдена.", tg_id, message_id)
        else:
             bot.send_message(tg_id, "Ошибка: Игра не найдена.")
        return
        
    if game[3] != tg_id:
        bot.send_message(tg_id, "У вас нет прав на управление этой игрой.")
        return

    game_name, budget, organizer_id, participants_json, status, invite_code, currency = game[1], game[2], game[3], game[4], game[5], game[6], game[7]
    participants = json.loads(participants_json)
    
    invite_link = f"https://t.me/{bot.get_me().username}?start={invite_code}"
    participants_list = "\n".join([f"- {get_user_link(p_id)}" for p_id in participants])
    
    text = (
        f"👑 <b>Панель Организатора: {game_name}</b>\n\n"
        f"<i>Бюджет:</i> <b>{budget} {currency}</b>\n"
        f"<i>Участников:</i> <b>{len(participants)}</b>\n"
        f"<i>Статус:</i> <b>{status}</b>\n\n"
        f"<b>Участники:</b>\n"
        f"{participants_list}\n"
    )

    if status == 'running':
        pairs = db_execute("SELECT santa_tg_id, recipient_tg_id, is_admin_pair FROM pairs WHERE game_id = ?", (game_id,), fetch_all=True)
        if pairs:
            text += "\n--- 👥 <b>Пары</b> ---\n"
            for santa_id, recipient_id, is_admin_pair in pairs:
                santa_link = get_user_link(santa_id)
                recipient_link = get_user_link(recipient_id)
                source = " (Ручн.)" if is_admin_pair else ""
                text += f"🎅 {santa_link} ➡️ 🎁 {recipient_link}{source}\n"
        else:
            text += "\n--- 👥 Пары ---\nЖеребьевка не дала результатов.\n"
            
    text += (
        f"\n<b>Ссылка для приглашения:</b>\n"
        f"<code>{invite_link}</code>"
    )

    markup = types.InlineKeyboardMarkup()
    
    if len(participants) < 2 and status == 'setup':
         markup.add(types.InlineKeyboardButton("🚫 Нельзя начать (нужно минимум 2)", callback_data='noop'))
    elif status == 'setup':
        markup.add(types.InlineKeyboardButton(f"🎲 Провести жеребьёвку", callback_data=f'draw_{game_id}'))
    elif status == 'running':
        markup.add(types.InlineKeyboardButton("🔄 Пережеребьёвка", callback_data=f'draw_{game_id}'))
        markup.add(types.InlineKeyboardButton("🎁 Завершить игру", callback_data=f'finish_game_{game_id}'))
    
    markup.add(types.InlineKeyboardButton("🗑️️ Удалить игру", callback_data=f'delete_game_{game_id}'))
    markup.add(types.InlineKeyboardButton("⬅️ Назад в Мои игры", callback_data='my_games'))
    
    if message_id:
        try:
            bot.edit_message_text(text, tg_id, message_id, reply_markup=markup, parse_mode='HTML')
        except telebot.apihelper.ApiTelegramException as e:
            if 'message is not modified' not in str(e):
                raise e
    else:
        bot.send_message(tg_id, text, reply_markup=markup, parse_mode='HTML')

def participant_game_view(bot, call, game_id):
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
        
    organizer_link = get_user_link(organizer_id)
    text = f"🎁 <b>Информация об игре: {game_name}</b>\n\n"
    text += f"<i>Организатор:</i> {organizer_link}\n"
    text += f"<i>Бюджет:</i> <b>{budget} {currency}</b>\n"
    text += f"<i>Статус:</i> <b>{status}</b>\n"
    
    markup = types.InlineKeyboardMarkup()
    
    if status == 'running':
        pair = db_execute("SELECT recipient_tg_id FROM pairs WHERE santa_tg_id = ? AND game_id = ?", (tg_id, game_id), fetch_one=True)
        
        if pair:
            recipient_id = pair[0]
            recipient_link = get_user_link(recipient_id)
            
            recipient_wishes = db_execute(
                "SELECT text FROM wishes WHERE user_tg_id = ? AND game_id = ?", 
                (recipient_id, game_id), 
                fetch_one=True
            )
            wish_text = recipient_wishes[0] if recipient_wishes else "Пожелания пока не указаны."

            text += "\n--- 🎅 ---\n"
            text += f"Ваш Тайный Подопечный: <b>{recipient_link}</b>\n\n"
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

def my_games_panel(bot, call):
    tg_id = call.from_user.id
    message_id = call.message.message_id
    
    org_games = db_execute("SELECT id, name, status FROM games WHERE organizer_id = ?", (tg_id,), fetch_all=True)
    all_games = db_execute("SELECT id, name, participants_json, organizer_id, status FROM games", fetch_all=True)
    
    participant_games = []
    wish_games = []
    
    for game_id, name, participants_json, organizer_id, status in all_games:
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

    try:
        bot.edit_message_text(text, tg_id, message_id, reply_markup=markup, parse_mode='HTML')
    except telebot.apihelper.ApiTelegramException as e:
        if 'message is not modified' not in str(e):
            raise e