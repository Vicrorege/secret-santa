import sqlite3
import os
import json

DB_NAME = os.getenv('DB_NAME', 'secret_santa.db') 

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

def get_table_data(table_name, page_num=0, page_size=10):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    count = cursor.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    
    offset = page_num * page_size
    data = cursor.execute(f"SELECT * FROM {table_name} LIMIT {page_size} OFFSET {offset}").fetchall()
    
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

def get_game_info(game_id):
    return db_execute("SELECT id, name, budget, organizer_id, participants_json, status, invite_code, currency FROM games WHERE id = ?", (game_id,), fetch_one=True)

def is_admin(tg_id):
    user = get_user_info(tg_id)
    return user and user[5] == 'admin'

# Добавлено для устранения ошибки импорта в main.py
def get_game_id_by_code(invite_code):
    result = db_execute("SELECT id FROM games WHERE invite_code = ?", (invite_code,), fetch_one=True)
    return result[0] if result else None