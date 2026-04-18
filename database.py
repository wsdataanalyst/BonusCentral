"""
Database - Gerenciamento do banco de dados SQLite
"""

import sqlite3
import hashlib
import os
from datetime import datetime

DB_PATH = "vendas.db"

def get_connection():
    """Retorna conexão com o banco de dados"""
    return sqlite3.connect(DB_PATH)

def init_database():
    """Inicializa todas as tabelas do banco de dados"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabela de usuários
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_admin INTEGER DEFAULT 0
        )
    ''')
    
    # Tabela de análises (histórico)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            periodo TEXT NOT NULL,
            data_analise TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dados_json TEXT NOT NULL,
            total_bonus REAL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')
    
    # Tabela de logs de acesso
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs_acesso (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            ip TEXT,
            data_acesso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            acao TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')
    
    conn.commit()
    
    # Criar usuário admin padrão se não existir
    cursor.execute("SELECT * FROM usuarios WHERE username = 'admin'")
    if not cursor.fetchone():
        password_hash = hashlib.sha256("admin123".encode()).hexdigest()
        cursor.execute(
            "INSERT INTO usuarios (username, password_hash, is_admin) VALUES (?, ?, 1)",
            ("admin", password_hash)
        )
        conn.commit()
        print("Usuário admin criado: admin / admin123")
    
    conn.close()

def salvar_analise(usuario_id, periodo, dados_json, total_bonus):
    """Salva uma análise no histórico"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO analises (usuario_id, periodo, dados_json, total_bonus) VALUES (?, ?, ?, ?)",
        (usuario_id, periodo, dados_json, total_bonus)
    )
    conn.commit()
    analise_id = cursor.lastrowid
    conn.close()
    return analise_id

def get_analises_usuario(usuario_id):
    """Retorna todas as análises de um usuário"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, periodo, data_analise, dados_json, total_bonus FROM analises WHERE usuario_id = ? ORDER BY data_analise DESC",
        (usuario_id,)
    )
    analises = cursor.fetchall()
    conn.close()
    
    result = []
    for a in analises:
        result.append({
            'id': a[0],
            'periodo': a[1],
            'data_analise': a[2],
            'dados_json': a[3],
            'total_bonus': a[4]
        })
    return result

def get_analise_by_id(analise_id, usuario_id):
    """Retorna uma análise específica"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM analises WHERE id = ? AND usuario_id = ?",
        (analise_id, usuario_id)
    )
    analise = cursor.fetchone()
    conn.close()
    return analise

def registrar_log(usuario_id, ip, acao):
    """Registra log de acesso"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO logs_acesso (usuario_id, ip, acao) VALUES (?, ?, ?)",
        (usuario_id, ip, acao)
    )
    conn.commit()
    conn.close()