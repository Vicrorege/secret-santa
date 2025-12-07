import json
import random
import sqlite3
from telebot import types
from db_manager import db_execute, get_game_info, is_admin # <-- Добавлен is_admin
from bot_handlers.common import get_user_link, get_user_name, main_menu_markup
from bot_handlers.game_panels import organizer_panel 

def join_game_prompt(bot, message, game_id):
    tg_id = message.chat.id
    game = get_game_info(game_id)
    
    if not game:
        bot.send_message(tg_id, "Игра не найдена. Возможно, она была удалена.")
        return
        
    game_name, budget, organizer_id, participants_json, status, invite_code, currency = game[1], game[2], game[3], game[4], game[5], game[6], game[7]
    organizer_link = get_user_link(organizer_id)
    participants = json.loads(participants_json)
    
    if tg_id in participants:
        bot.send_message(tg_id, f"Вы уже являетесь участником игры <b>'{game_name}'</b>.", parse_mode='HTML')
        return

    text = (
        f"Вас пригласили в игру Тайного Санты <b>'{game_name}'</b>!\n\n"
        f"<i>Организатор:</i> {organizer_link}\n"
        f"<i>Максимальный бюджет:</i> <b>{budget} {currency}</b>\n"
        f"<i>Участников сейчас:</i> {len(participants)}"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Присоединиться", callback_data=f'join_{game_id}'))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data='menu'))

    bot.send_message(tg_id, text, reply_markup=markup, parse_mode='HTML')

def join_game_action(bot, call, game_id):
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

def draw_pairs(bot, game_id, tg_id):
    game = get_game_info(game_id)
    
    # *** ИЗМЕНЕНИЕ: Проверка на Администратора, если tg_id не является Организатором ***
    if not game or (game[3] != tg_id and not is_admin(tg_id)):
        return "Ошибка: Игра не найдена или у вас нет прав организатора/администратора.", False
    
    game_name, budget, organizer_id, participants_json, status, invite_code, currency = game[1], game[2], game[3], game[4], game[5], game[6], game[7]
    all_participants = json.loads(game[4])
    
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
            recipient_link = get_user_link(recipient)
            recipient_wishes = db_execute(
                "SELECT text FROM wishes WHERE user_tg_id = ? AND game_id = ?", 
                (recipient, game_id), 
                fetch_one=True
            )
            
            wish_text = recipient_wishes[0] if recipient_wishes else "Пожелания пока не указаны."
            
            message_text = (
                f"🚨 <b>ЖЕРЕБЬЁВКА В ИГРЕ '{game_name}' ЗАВЕРШЕНА!</b> 🚨\n\n"
                f"Ваш Тайный Подопечный: <b>{recipient_link}</b>\n\n"
                f"🎁 <b>Пожелания для подарка:</b>\n"
                f"<i>{wish_text}</i>\n\n"
                f"💰 <i>Максимальный бюджет: {budget} {currency}</i>"
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

def finish_game_action(bot, call, game_id):
    tg_id = call.from_user.id
    game = get_game_info(game_id)
    
    if not game or (game[3] != tg_id and not is_admin(tg_id)):
        bot.answer_callback_query(call.id, "У вас нет прав.")
        return
        
    db_execute("UPDATE games SET status = 'finished' WHERE id = ?", (game_id,), commit=True)
    bot.answer_callback_query(call.id, f"Игра '{game[1]}' завершена!")
    organizer_panel(bot, tg_id, game_id, call.message.message_id)

# *** НОВАЯ ФУНКЦИЯ для команды /admin_action finish ***
def finish_game_action_admin(bot, game_id, tg_id):
    game = get_game_info(game_id)
    if not game or not is_admin(tg_id):
        return
        
    db_execute("UPDATE games SET status = 'finished' WHERE id = ?", (game_id,), commit=True)

def delete_game_confirm(bot, call, game_id):
    game = get_game_info(game_id)
    
    if not game or (game[3] != call.from_user.id and not is_admin(call.from_user.id)):
        bot.answer_callback_query(call.id, "У вас нет прав.")
        return
        
    text = f"⚠️ <b>Внимание!</b> Вы уверены, что хотите <b>безвозвратно</b> удалить игру <b>'{game[1]}'</b>?"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ ДА, удалить", callback_data=f'confirm_delete_{game_id}'))
    markup.add(types.InlineKeyboardButton("❌ НЕТ, отмена", callback_data=f'org_panel_{game_id}'))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

def delete_game_action(bot, call, game_id):
    tg_id = call.from_user.id
    game = get_game_info(game_id)
    
    if not game or (game[3] != tg_id and not is_admin(tg_id)):
        bot.answer_callback_query(call.id, "У вас нет прав.")
        return
        
    db_execute("DELETE FROM pairs WHERE game_id = ?", (game_id,), commit=True)
    db_execute("DELETE FROM wishes WHERE game_id = ?", (game_id,), commit=True)
    db_execute("DELETE FROM games WHERE id = ?", (game_id,), commit=True)
    
    bot.edit_message_text(f"🗑️ Игра <b>'{game[1]}'</b> и все связанные данные удалены.", tg_id, call.message.message_id, parse_mode='HTML')

def prompt_wish_text(bot, call, game_id, user_states):
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
    
def handle_wish_text(bot, message, user_states):
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