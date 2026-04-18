"""
Auth - Autenticação de usuários
"""

import hashlib
import streamlit as st
import re
from database import get_connection, registrar_log
import os

def hash_senha(senha):
    """Cria hash da senha usando SHA-256"""
    salt = "vendas_salt_2024"  # Salt fixo para consistência
    return hashlib.sha256(f"{senha}{salt}".encode()).hexdigest()

def validar_senha(senha):
    """Valida força da senha"""
    if len(senha) < 6:
        return False, "A senha deve ter no mínimo 6 caracteres"
    if not re.search(r"[A-Za-z]", senha):
        return False, "A senha deve conter letras"
    if not re.search(r"[0-9]", senha):
        return False, "A senha deve conter números"
    return True, "OK"

def registrar_usuario(username, password, email=""):
    """Registra um novo usuário"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Verifica se usuário já existe
    cursor.execute("SELECT id FROM usuarios WHERE username = ?", (username,))
    if cursor.fetchone():
        conn.close()
        return False, "Usuário já existe"
    
    # Valida senha
    valido, msg = validar_senha(password)
    if not valido:
        conn.close()
        return False, msg
    
    # Cria usuário
    password_hash = hash_senha(password)
    try:
        cursor.execute(
            "INSERT INTO usuarios (username, password_hash, email) VALUES (?, ?, ?)",
            (username, password_hash, email)
        )
        conn.commit()
        conn.close()
        return True, "Usuário criado com sucesso!"
    except Exception as e:
        conn.close()
        return False, f"Erro ao criar usuário: {e}"

def fazer_login(username, password, ip=""):
    """Realiza login do usuário"""
    conn = get_connection()
    cursor = conn.cursor()
    
    password_hash = hash_senha(password)
    cursor.execute(
        "SELECT id, username, is_admin FROM usuarios WHERE username = ? AND password_hash = ?",
        (username, password_hash)
    )
    user = cursor.fetchone()
    
    if user:
        # Registra log de sucesso
        registrar_log(user[0], ip, "login_sucesso")
        conn.close()
        return {
            'id': user[0],
            'username': user[1],
            'is_admin': bool(user[2])
        }
    else:
        # Registra log de falha
        registrar_log(None, ip, "login_falha")
        conn.close()
        return None

def logout():
    """Realiza logout"""
    if 'usuario' in st.session_state:
        registrar_log(st.session_state['usuario']['id'], "", "logout")
    for key in ['usuario', 'logado', 'analise_atual', 'analise_realizada']:
        if key in st.session_state:
            del st.session_state[key]

def get_usuario_atual():
    """Retorna o usuário atual logado"""
    if st.session_state.get('logado', False):
        return st.session_state.get('usuario')
    return None

def is_admin():
    """Verifica se o usuário atual é admin"""
    usuario = get_usuario_atual()
    return usuario and usuario.get('is_admin', False)