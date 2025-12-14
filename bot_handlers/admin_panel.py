import telebot
from telebot import types
import json
from db_manager import db_execute, get_table_data, get_single_record, is_admin, is_fantom, get_game_info
from bot_handlers.common import get_user_link, get_user_name, escape_html, send

PAGE_SIZE = 10 

def admin_panel(bot, message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📦 Просмотр БД", callback_data='admin_view_db'))
    markup.add(types.InlineKeyboardButton("🎲 Назначить пары (Setup)", callback_data='admin_tweak_pairs'))
    markup.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data='menu'))

    try:
        bot.edit_message_text("👑 <b>Панель Администратора</b>", message.chat.id, message.message_id, reply_markup=markup, parse_mode='HTML')
    except:
        send(bot, message.chat.id, "ὅ1 <b>Панель Администратора</b>", reply_markup=markup, parse_mode='HTML')

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
        
        markup.add(*row)
        
    markup.add(types.InlineKeyboardButton("❌ Закрыть / Назад в таблицы", callback_data='admin_view_db'))
    return markup

def admin_view_db_tables(bot, call):
    if not is_admin(call.from_user.id): return
    
    tables = db_execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'", fetch_all=True)
    
    text = "📂 <b>Выберите таблицу для просмотра/изменения:</b>"
    markup = types.InlineKeyboardMarkup()
    
    for table in tables:
        markup.add(types.InlineKeyboardButton(table[0], callback_data=f'admin_db_table_{table[0]}_0'))
        
    markup.add(types.InlineKeyboardButton("⬅️ Назад в Админ-панель", callback_data='admin_menu'))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except telebot.apihelper.ApiTelegramException as e:
        if 'message is not modified' not in str(e):
            raise e

def admin_view_table_data(bot, call, table_name, page):
    if not is_admin(call.from_user.id): return
    
    columns, data, total_count = get_table_data(table_name, page, PAGE_SIZE)
    
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
    
    final_markup = types.InlineKeyboardMarkup()
    final_markup.keyboard.extend(main_markup.keyboard)
    final_markup.keyboard.extend(pagination_markup.keyboard)
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=final_markup, parse_mode='HTML')
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка отображения: {e}")
        admin_view_db_tables(bot, call)


def admin_edit_record_view(bot, call, table_name, record_id):
    if not is_admin(call.from_user.id): return
    
    columns, record = get_single_record(table_name, record_id)
    if not record:
        bot.answer_callback_query(call.id, "Запись не найдена.")
        admin_view_db_tables(bot, call)
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

    edit_markup.add(types.InlineKeyboardButton("🗑️ Удалить запись", callback_data=f'admin_delete_record_{table_name}_{record[0]}'))
    edit_markup.add(types.InlineKeyboardButton("⬅️ Назад к таблице", callback_data=f'admin_db_table_{table_name}_0'))
    
    if call.message and call.message.message_id:
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=edit_markup, parse_mode='HTML')
        except telebot.apihelper.ApiTelegramException as e:
            if 'message is not modified' not in str(e):
                raise e
    else:
        send(bot, call.message.chat.id, text, reply_markup=edit_markup, parse_mode='HTML')


def admin_prompt_edit_value(bot, call, table_name, record_id, col_name, user_states):
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
    
    send(bot, call.message.chat.id, text, parse_mode='HTML')
    bot.answer_callback_query(call.id)
    

def handle_admin_edit_input(bot, message, user_states):
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
        
        send(
            bot, tg_id, 
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
            admin_edit_record_view(bot, mock_call, table_name, record_id)
        except Exception:
            mock_call.message.message_id = None 
            admin_edit_record_view(bot, mock_call, table_name, record_id)
            
    except Exception as e:
        send(
            bot, tg_id, 
            f"❌ Ошибка при обновлении поля: {str(e)}", 
            parse_mode='HTML'
        )


def admin_confirm_delete_record(bot, call, table_name, record_id):
    if not is_admin(call.from_user.id): return

    text = f"⚠️ <b>Подтвердите удаление записи</b>\nТаблица: <b>{table_name}</b>, ID: <b>{record_id}</b>\n\nЭто действие необратимо."
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Удалить", callback_data=f'admin_execute_delete_record_{table_name}_{record_id}'))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f'admin_edit_record_{table_name}_{record_id}'))

    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except telebot.apihelper.ApiTelegramException as e:
        if 'message is not modified' not in str(e):
            raise e


def admin_execute_delete_record(bot, call, table_name, record_id):
    if not is_admin(call.from_user.id): return
    if not table_name:
        bot.answer_callback_query(call.id, "Не указано имя таблицы.")
        admin_view_db_tables(bot, call)
        return

    # Проверим, есть ли такая таблица в БД
    exists = db_execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table_name,), fetch_one=True)
    if not exists:
        bot.answer_callback_query(call.id, f"Таблица '{table_name}' не найдена.")
        admin_view_db_tables(bot, call)
        return

    # Безопасно экранируем идентификаторы (удаляем/экранируем двойные кавычки)
    safe_table = '"' + table_name.replace('"', '""') + '"'

    # Узнаём имя первичного ключа (через PRAGMA для безопасной таблицы)
    cols = db_execute(f"PRAGMA table_info({safe_table})", fetch_all=True)
    if not cols:
        bot.answer_callback_query(call.id, "Не удалось получить информацию о таблице (PRAGMA вернуло пусто).")
        admin_view_db_tables(bot, call)
        return

    pk_name = cols[0][1]
    safe_pk = '"' + pk_name.replace('"', '""') + '"'

    try:
        db_execute(f"DELETE FROM {safe_table} WHERE {safe_pk} = ?", (record_id,), commit=True)
        bot.answer_callback_query(call.id, f"✅ Запись {record_id} удалена из таблицы {table_name}.")
        # Показать таблицу заново (страница 0)
        admin_view_table_data(bot, call, table_name, 0)
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка при удалении: {e}")
        admin_view_table_data(bot, call, table_name, 0)

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

def admin_tweak_pairs_select_game(bot, call):
    if not is_admin(call.from_user.id): return
    markup = get_admin_game_select_markup('admin_tweak_game')
    bot.edit_message_text("Выберите игру для назначения пар (статус 'setup'):", call.message.chat.id, call.message.message_id, reply_markup=markup)

def admin_tweak_pairs_show(bot, call, game_id):
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
            santa_link = get_user_link(santa_id)
            recipient_link = get_user_link(recipient_id)
            text += f"<b>{santa_link}</b> ➡️ <b>{recipient_link}</b>\n"
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
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except telebot.apihelper.ApiTelegramException as e:
        if 'message is not modified' not in str(e):
            raise e

def admin_assign_recipient_start(bot, call, game_id, santa_id):
    if not is_admin(call.from_user.id): return
    game = get_game_info(game_id)
    participants = json.loads(game[4])
    
    santa_link = get_user_link(santa_id)

    text = f"<b>Назначение получателя для {santa_link}</b>\n\nВыберите получателя:"
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
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except telebot.apihelper.ApiTelegramException as e:
        if 'message is not modified' not in str(e):
            raise e
    
def admin_assign_recipient_execute(bot, call, game_id, santa_id, recipient_id):
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
    admin_tweak_pairs_show(bot, call, game_id)
    
def admin_delete_manual_pairs_action(bot, call, game_id):
    if not is_admin(call.from_user.id): return
    
    db_execute("DELETE FROM pairs WHERE game_id = ? AND is_admin_pair = 1", (game_id,), commit=True)
    
    bot.answer_callback_query(call.id, "❌ Все ручные пары удалены!")
    admin_tweak_pairs_show(bot, call, game_id)

def callback_admin_panel(bot, call, user_states):
    if is_fantom(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Вам запрещено использовать этот бот.", show_alert=True)
        return
    
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "У вас нет прав администратора.", show_alert=True)
        return
        
    data = call.data
    
    if data == 'admin_menu':
        admin_panel(bot, call.message)
    elif data == 'admin_tweak_pairs':
        admin_tweak_pairs_select_game(bot, call)
    elif data.startswith('admin_tweak_game_'):
        payload = data[len('admin_tweak_game_'):]
        try:
            game_id = int(payload)
        except Exception:
            bot.answer_callback_query(call.id, "Неверный идентификатор игры.")
            return
        admin_tweak_pairs_show(bot, call, game_id)
    elif data.startswith('admin_assign_recipient_start_'):
        payload = data[len('admin_assign_recipient_start_'):]
        try:
            game_id_str, santa_id_str = payload.split('_', 1)
            game_id, santa_id = int(game_id_str), int(santa_id_str)
        except Exception:
            bot.answer_callback_query(call.id, "Неверные параметры назначения получателя.")
            return
        admin_assign_recipient_start(bot, call, game_id, santa_id)
    elif data.startswith('admin_assign_recipient_execute_'):
        payload = data[len('admin_assign_recipient_execute_'):]
        try:
            parts = payload.split('_')
            game_id, santa_id, recipient_id = int(parts[0]), int(parts[1]), int(parts[2])
        except Exception:
            bot.answer_callback_query(call.id, "Неверные параметры назначения получателя.")
            return
        admin_assign_recipient_execute(bot, call, game_id, santa_id, recipient_id)
    elif data.startswith('admin_delete_manual_pairs_'):
        payload = data[len('admin_delete_manual_pairs_'):]
        try:
            game_id = int(payload)
        except Exception:
            bot.answer_callback_query(call.id, "Неверный идентификатор игры.")
            return
        admin_delete_manual_pairs_action(bot, call, game_id)
    elif data == 'admin_view_db':
        admin_view_db_tables(bot, call)
    elif data.startswith('admin_db_table_'):
        payload = data[len('admin_db_table_'):]
        try:
            table_name, page_str = payload.rsplit('_', 1)
            page = int(page_str)
        except Exception:
            bot.answer_callback_query(call.id, "Неверные параметры таблицы.")
            return
        admin_view_table_data(bot, call, table_name, page)
    elif data.startswith('admin_db_page_'):
        payload = data[len('admin_db_page_'):]
        try:
            table_name, page_str = payload.rsplit('_', 1)
            page = int(page_str)
        except Exception:
            bot.answer_callback_query(call.id, "Неверные параметры страницы.")
            return
        admin_view_table_data(bot, call, table_name, page)
    elif data.startswith('admin_prompt_edit_'):
        payload = data[len('admin_prompt_edit_'):]
        try:
            table_name, record_id_str, col_name = payload.rsplit('_', 2)
            record_id = int(record_id_str)
        except Exception:
            bot.answer_callback_query(call.id, "Неверные параметры редактирования.")
            return
        admin_prompt_edit_value(bot, call, table_name, record_id, col_name, user_states)
    elif data.startswith('admin_edit_record_'):
        payload = data[len('admin_edit_record_'):]
        try:
            table_name, record_id_str = payload.rsplit('_', 1)
            record_id = int(record_id_str)
        except Exception:
            bot.answer_callback_query(call.id, "Неверные параметры просмотра записи.")
            return
        admin_edit_record_view(bot, call, table_name, record_id)
    elif data.startswith('admin_delete_record_'):
        parts = data.split('_')
        # support table names containing underscores: last part is id
        record_id = int(parts[-1])
        table_name = '_'.join(parts[3:-1])
        admin_confirm_delete_record(bot, call, table_name, record_id)
    elif data.startswith('admin_execute_delete_record_'):
        parts = data.split('_')
        record_id = int(parts[-1])
        table_name = '_'.join(parts[3:-1])
        admin_execute_delete_record(bot, call, table_name, record_id)
    else:
        bot.answer_callback_query(call.id, f"Действие '{data}' пока не реализовано.")

def admin_update_all_users_data(bot, message):
    if is_fantom(message.from_user.id):
        return "❌ Вам запрещено использовать этот бот.", False
    
    if not is_admin(message.from_user.id):
        return "❌ У вас нет прав администратора.", False

    # Получаем все tg_id из базы данных
    all_user_ids = db_execute("SELECT tg_id FROM users", fetch_all=True)
    
    if not all_user_ids:
        return "⚠️ В базе данных нет пользователей для обновления.", False

    updated_count = 0
    
    # Отправляем сообщение, чтобы избежать таймаута при длительной операции
    status_msg = send(bot, message.chat.id, "🔄 **Начинаю обновление данных всех пользователей...**", parse_mode='Markdown')

    for user_id_tuple in all_user_ids:
        tg_id = user_id_tuple[0]
        try:
            # Получаем актуальную информацию из Telegram API
            member = bot.get_chat_member(tg_id, tg_id)
            user = member.user
            
            # Подготовка данных
            username = user.username
            first_name = user.first_name
            last_name = user.last_name
            
            # Обновление записи в БД
            db_execute(
                "UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE tg_id = ?",
                (username, first_name, last_name, tg_id),
                commit=True
            )
            updated_count += 1
            
        except telebot.apihelper.ApiTelegramException as e:
            # Обработка случаев, когда бот не может получить информацию
            # Например, если пользователь заблокировал бота, tg_id становится недоступным
            if 'user not found' in str(e) or 'is not a member' in str(e):
                # Можно добавить логику для пометки или удаления "мертвых" аккаунтов
                pass
            else:
                pass 
        except Exception:
            pass
            
    bot.delete_message(message.chat.id, status_msg.message_id)

    return f"✅ **Успешно обновлено {updated_count}** из {len(all_user_ids)} записей пользователей.", True

# Добавьте эту функцию в callback_admin_panel, чтобы можно было вызывать ее из меню
def admin_prompt_update_all_users(bot, call):
    text = "⚠️ **Вы уверены, что хотите обновить данные всех пользователей?** Это может занять некоторое время."
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ ДА, обновить сейчас", callback_data='admin_execute_update_users'))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data='admin_menu'))

    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

def admin_execute_update_users_action(bot, call):
    tg_id = call.from_user.id
    bot.answer_callback_query(call.id, "Начинаю обновление...", show_alert=False)
    
    result_text, success = admin_update_all_users_data(bot, call.message)
    
    bot.edit_message_text(
        result_text, 
        tg_id, 
        call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️ Назад", callback_data='admin_menu')),
        parse_mode='Markdown'
    )