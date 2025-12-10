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

def is_fantom(tg_id):
    """Проверить, имеет ли пользователь роль 'fantom'."""
    user = get_user_info(tg_id)
    return user and user[5] == 'fantom'

# Добавлено для устранения ошибки импорта в main.py
def get_game_id_by_code(invite_code):
    result = db_execute("SELECT id FROM games WHERE invite_code = ?", (invite_code,), fetch_one=True)
    return result[0] if result else None

class User:
    """
    Класс для управления пользователями в системе Secret Santa.
    Поддерживает инициализацию через id или tg_id.
    """
    
    def __init__(self, id=None, tg_id=None):
        """
        Инициализация пользователя.
        
        Args:
            id (int): ID пользователя в БД
            tg_id (int): Telegram ID пользователя
            
        Raises:
            ValueError: Если не указаны ни id ни tg_id
        """
        if id is None and tg_id is None:
            raise ValueError("Необходимо указать либо id, либо tg_id")
        
        self.id = None
        self.tg_id = None
        self.username = None
        self.first_name = None
        self.last_name = None
        self.role = None
        
        # Загружаем данные из БД
        if id is not None:
            self._load_by_id(id)
        elif tg_id is not None:
            self._load_by_tg_id(tg_id)
    
    @staticmethod
    def get_fantom(tg_id):
        """
        Получить фантома - специального пользователя с заданым id.
        Если его нет в БД, создать.
        
        Returns:
            User: Объект пользователя-фантома
        """
        try:
            return User(tg_id=0)
        except ValueError:
            return User.create_user(tg_id=tg_id, username='fantom', first_name='Fantom', role='fantom')

    @staticmethod
    def create_user(tg_id, username=None, first_name=None, last_name=None, role='user'):
        """
        Создать нового пользователя и добавить в БД.
        
        Args:
            tg_id (int): Telegram ID пользователя (обязательно)
            username (str): Имя пользователя в Telegram (опционально)
            first_name (str): Имя пользователя (опционально)
            last_name (str): Фамилия пользователя (опционально)
            role (str): Роль пользователя ('user' или 'admin'), по умолчанию 'user'
            
        Returns:
            User: Объект созданного пользователя
            
        Raises:
            ValueError: Если пользователь с таким tg_id уже существует
        """
        # Проверяем, не существует ли пользователь
        existing_user = db_execute(
            "SELECT tg_id FROM users WHERE tg_id = ?",
            (tg_id,),
            fetch_one=True
        )
        
        if existing_user:
            raise ValueError(f"Пользователь с tg_id {tg_id} уже существует в БД")
        
        # Добавляем нового пользователя
        db_execute(
            """INSERT INTO users (tg_id, username, first_name, last_name, role) 
               VALUES (?, ?, ?, ?, ?)""",
            (tg_id, username, first_name, last_name, role),
            commit=True
        )
        
        # Возвращаем объект User с загруженными данными
        return User(tg_id=tg_id)
    
    @staticmethod
    def get_or_create(tg_id, username=None, first_name=None, last_name=None, role='user'):
        """
        Получить пользователя из БД или создать нового, если его еще нет.
        
        Args:
            tg_id (int): Telegram ID пользователя (обязательно)
            username (str): Имя пользователя в Telegram (используется при создании)
            first_name (str): Имя пользователя (используется при создании)
            last_name (str): Фамилия пользователя (используется при создании)
            role (str): Роль пользователя (используется при создании)
            
        Returns:
            User: Объект существующего или созданного пользователя
        """
        try:
            # Пытаемся загрузить существующего пользователя
            return User(tg_id=tg_id)
        except ValueError:
            # Если не найден, создаем нового
            return User.create_user(tg_id, username, first_name, last_name, role)
    
    def _load_by_id(self, user_id):
        """Загрузить данные пользователя по его ID в БД."""
        user_data = db_execute(
            "SELECT id, tg_id, username, first_name, last_name, role FROM users WHERE id = ?",
            (user_id,),
            fetch_one=True
        )
        
        if user_data:
            self.id, self.tg_id, self.username, self.first_name, self.last_name, self.role = user_data
        else:
            raise ValueError(f"Пользователь с ID {user_id} не найден в БД")
    
    def _load_by_tg_id(self, tg_id):
        """Загрузить данные пользователя по его Telegram ID."""
        user_data = db_execute(
            "SELECT id, tg_id, username, first_name, last_name, role FROM users WHERE tg_id = ?",
            (tg_id,),
            fetch_one=True
        )
        
        if user_data:
            self.id, self.tg_id, self.username, self.first_name, self.last_name, self.role = user_data
        else:
            raise ValueError(f"Пользователь с tg_id {tg_id} не найден в БД")
    
    def save(self):
        """Сохранить/обновить данные пользователя в БД."""
        if self.id is None:
            # Новый пользователь - вставляем
            db_execute(
                """INSERT INTO users (tg_id, username, first_name, last_name, role) 
                   VALUES (?, ?, ?, ?, ?)""",
                (self.tg_id, self.username, self.first_name, self.last_name, self.role or 'user'),
                commit=True
            )
            # Получаем ID новой записи
            user_data = db_execute(
                "SELECT id FROM users WHERE tg_id = ?",
                (self.tg_id,),
                fetch_one=True
            )
            self.id = user_data[0]
        else:
            # Обновляем существующего пользователя
            db_execute(
                """UPDATE users 
                   SET tg_id = ?, username = ?, first_name = ?, last_name = ?, role = ? 
                   WHERE id = ?""",
                (self.tg_id, self.username, self.first_name, self.last_name, self.role, self.id),
                commit=True
            )
    
    def is_admin(self):
        """Проверить, является ли пользователь администратором."""
        return self.role == 'admin'
    
    def is_fantom(self):
        """Проверить, является ли пользователь фантомом (заблокированным)."""
        return self.role == 'fantom'
    
    def set_admin(self, is_admin=True):
        """Установить/убрать права администратора."""
        self.role = 'admin' if is_admin else 'user'
        self.save()
    
    def set_fantom(self, is_fantom=True):
        """Установить/убрать статус фантома (блокировка пользователя)."""
        self.role = 'fantom' if is_fantom else 'user'
        self.save()
    
    def get_full_name(self):
        """Получить полное имя пользователя."""
        name_parts = [self.first_name, self.last_name]
        full_name = ' '.join([p for p in name_parts if p])
        return full_name or self.username or f"ID: {self.tg_id}"
    
    def get_games_as_organizer(self):
        """Получить список игр, где пользователь является организатором."""
        games = db_execute(
            "SELECT id, name, status FROM games WHERE organizer_id = ? ORDER BY id DESC",
            (self.tg_id,),
            fetch_all=True
        )
        return games or []
    
    def get_games_as_participant(self):
        """Получить список игр, где пользователь является участником."""
        all_games = db_execute(
            "SELECT id, name, participants_json, organizer_id, status FROM games",
            fetch_all=True
        )
        
        participant_games = []
        for game_id, name, participants_json, organizer_id, status in all_games:
            participants = json.loads(participants_json)
            if self.tg_id in participants:
                participant_games.append((game_id, name, status))
        
        return participant_games
    
    def delete(self):
        """Удалить пользователя из БД."""
        if self.id is not None:
            db_execute("DELETE FROM users WHERE id = ?", (self.id,), commit=True)
            self.id = None
    
    def __repr__(self):
        """Строковое представление объекта."""
        return f"User(id={self.id}, tg_id={self.tg_id}, username={self.username}, role={self.role})"
    
    def __str__(self):
        """Читаемое представление объекта."""
        return f"{self.get_full_name()} (ID: {self.tg_id}, role: {self.role})"