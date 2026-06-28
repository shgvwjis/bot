"""
数据库模块 - SQLite 版本
支持：Bot配置、用户验证、黑名单、消息映射、欢迎语
"""
import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "bot_data.db")

def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """初始化数据库表"""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Bot 配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bots (
            bot_username TEXT PRIMARY KEY,
            token TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            welcome_msg TEXT,
            mode TEXT DEFAULT 'direct',
            forum_group_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. 已验证用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS verified_users (
            bot_username TEXT,
            user_id INTEGER,
            user_name TEXT,
            user_username TEXT,
            verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (bot_username, user_id)
        )
    ''')

    # 3. 黑名单表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            bot_username TEXT,
            user_id INTEGER,
            reason TEXT,
            blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (bot_username, user_id)
        )
    ''')

    # 4. 消息映射表（统一存储各种映射）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mappings (
            bot_username TEXT,
            map_type TEXT,
            key TEXT,
            value TEXT,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (bot_username, map_type, key)
        )
    ''')

    # 5. 待验证用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_verifications (
            bot_username TEXT,
            user_id INTEGER,
            captcha_answer TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (bot_username, user_id)
        )
    ''')

    # 6. 全局设置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")

# ==================== Bot 配置 ====================
def add_bot(bot_username: str, token: str, owner_id: int, welcome_msg: str = ''):
    """添加 Bot"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO bots (bot_username, token, owner_id, welcome_msg, mode)
        VALUES (?, ?, ?, ?, 'direct')
    ''', (bot_username, token, owner_id, welcome_msg))
    conn.commit()
    conn.close()

def get_bot(bot_username: str) -> Optional[Dict]:
    """获取单个 Bot 配置"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM bots WHERE bot_username = ?', (bot_username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_bots() -> Dict[str, Dict]:
    """获取所有 Bot 配置，返回 {bot_username: {...}}"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM bots')
    rows = cursor.fetchall()
    conn.close()
    return {row['bot_username']: dict(row) for row in rows}

def update_bot_mode(bot_username: str, mode: str):
    """更新 Bot 模式"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE bots SET mode = ? WHERE bot_username = ?', (mode, bot_username))
    conn.commit()
    conn.close()

def update_bot_forum_id(bot_username: str, forum_group_id: int):
    """更新 Bot 话题群 ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE bots SET forum_group_id = ? WHERE bot_username = ?', (forum_group_id, bot_username))
    conn.commit()
    conn.close()

def update_bot_welcome(bot_username: str, welcome_msg: str) -> bool:
    """更新 Bot 欢迎语"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE bots SET welcome_msg = ? WHERE bot_username = ?', (welcome_msg, bot_username))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def delete_bot(bot_username: str):
    """删除 Bot（级联删除相关数据）"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM bots WHERE bot_username = ?', (bot_username,))
    cursor.execute('DELETE FROM verified_users WHERE bot_username = ?', (bot_username,))
    cursor.execute('DELETE FROM blacklist WHERE bot_username = ?', (bot_username,))
    cursor.execute('DELETE FROM mappings WHERE bot_username = ?', (bot_username,))
    cursor.execute('DELETE FROM pending_verifications WHERE bot_username = ?', (bot_username,))
    conn.commit()
    conn.close()

# ==================== 验证用户 ====================
def is_verified(bot_username: str, user_id: int) -> bool:
    """检查用户是否已验证"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM verified_users WHERE bot_username = ? AND user_id = ?', (bot_username, user_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def add_verified_user(bot_username: str, user_id: int, user_name: str = '', user_username: str = ''):
    """添加已验证用户"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO verified_users (bot_username, user_id, user_name, user_username)
        VALUES (?, ?, ?, ?)
    ''', (bot_username, user_id, user_name, user_username))
    conn.commit()
    conn.close()

def remove_verified_user(bot_username: str, user_id: int) -> bool:
    """取消用户验证"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM verified_users WHERE bot_username = ? AND user_id = ?', (bot_username, user_id))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def get_verified_users(bot_username: str) -> List[Dict]:
    """获取所有已验证用户"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM verified_users WHERE bot_username = ?', (bot_username,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ==================== 黑名单 ====================
def is_blacklisted(bot_username: str, user_id: int) -> bool:
    """检查用户是否在黑名单中"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM blacklist WHERE bot_username = ? AND user_id = ?', (bot_username, user_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def add_to_blacklist(bot_username: str, user_id: int, reason: str = '') -> bool:
    """添加黑名单，返回是否成功（True=新增，False=已存在）"""
    if is_blacklisted(bot_username, user_id):
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO blacklist (bot_username, user_id, reason) VALUES (?, ?, ?)', (bot_username, user_id, reason))
    conn.commit()
    conn.close()
    return True

def remove_from_blacklist(bot_username: str, user_id: int) -> bool:
    """从黑名单移除"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM blacklist WHERE bot_username = ? AND user_id = ?', (bot_username, user_id))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def get_blacklist(bot_username: str) -> List[int]:
    """获取黑名单用户 ID 列表"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM blacklist WHERE bot_username = ?', (bot_username,))
    rows = cursor.fetchall()
    conn.close()
    return [row['user_id'] for row in rows]

def get_blacklist_count(bot_username: str) -> int:
    """获取黑名单数量"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as count FROM blacklist WHERE bot_username = ?', (bot_username,))
    row = cursor.fetchone()
    conn.close()
    return row['count'] if row else 0

# ==================== 消息映射 ====================
def set_mapping(bot_username: str, map_type: str, key: str, value: str, user_id: int):
    """设置映射关系"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO mappings (bot_username, map_type, key, value, user_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (bot_username, map_type, key, value, user_id))
    conn.commit()
    conn.close()

def get_mapping(bot_username: str, map_type: str, key: str) -> Optional[str]:
    """获取映射值"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM mappings WHERE bot_username = ? AND map_type = ? AND key = ?', (bot_username, map_type, key))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else None

def get_all_mappings(bot_username: str, map_type: str) -> Dict[str, str]:
    """获取所有映射 {key: value}"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT key, value FROM mappings WHERE bot_username = ? AND map_type = ?', (bot_username, map_type))
    rows = cursor.fetchall()
    conn.close()
    return {row['key']: row['value'] for row in rows}

def delete_mapping(bot_username: str, map_type: str, key: str):
    """删除映射"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM mappings WHERE bot_username = ? AND map_type = ? AND key = ?', (bot_username, map_type, key))
    conn.commit()
    conn.close()

# ==================== 待验证用户 ====================
def add_pending_verification(bot_username: str, user_id: int, captcha_answer: str):
    """添加待验证用户"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO pending_verifications (bot_username, user_id, captcha_answer)
        VALUES (?, ?, ?)
    ''', (bot_username, user_id, captcha_answer))
    conn.commit()
    conn.close()

def get_pending_verification(bot_username: str, user_id: int) -> Optional[str]:
    """获取待验证用户的验证码答案"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT captcha_answer FROM pending_verifications WHERE bot_username = ? AND user_id = ?', (bot_username, user_id))
    row = cursor.fetchone()
    conn.close()
    return row['captcha_answer'] if row else None

def remove_pending_verification(bot_username: str, user_id: int):
    """删除待验证记录"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM pending_verifications WHERE bot_username = ? AND user_id = ?', (bot_username, user_id))
    conn.commit()
    conn.close()

# ==================== 全局设置 ====================
def set_global_welcome(welcome_msg: str) -> bool:
    """设置全局欢迎语"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)', ('global_welcome', welcome_msg))
    conn.commit()
    conn.close()
    return True

def get_global_welcome() -> Optional[str]:
    """获取全局欢迎语"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM global_settings WHERE key = ?', ('global_welcome',))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else None

def delete_global_welcome() -> bool:
    """删除全局欢迎语"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM global_settings WHERE key = ?', ('global_welcome',))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

# ==================== 备份/恢复 ====================
def export_all_data() -> Dict:
    """导出所有数据（用于备份）"""
    conn = get_connection()
    cursor = conn.cursor()

    data = {}
    tables = ['bots', 'verified_users', 'blacklist', 'mappings', 'pending_verifications', 'global_settings']
    for table in tables:
        cursor.execute(f'SELECT * FROM {table}')
        rows = cursor.fetchall()
        data[table] = [dict(row) for row in rows]

    conn.close()
    return data

def import_all_data(data: Dict):
    """导入数据（用于恢复）"""
    conn = get_connection()
    cursor = conn.cursor()

    tables = ['bots', 'verified_users', 'blacklist', 'mappings', 'pending_verifications', 'global_settings']
    for table in tables:
        if table not in data:
            continue
        # 清空表
        cursor.execute(f'DELETE FROM {table}')
        if not data[table]:
            continue
        # 获取列名
        columns = list(data[table][0].keys())
        placeholders = ','.join(['?' for _ in columns])
        columns_str = ','.join(columns)
        for row in data[table]:
            values = [row.get(col) for col in columns]
            cursor.execute(f'INSERT OR REPLACE INTO {table} ({columns_str}) VALUES ({placeholders})', values)

    conn.commit()
    conn.close()

print("✅ database.py 加载完成")