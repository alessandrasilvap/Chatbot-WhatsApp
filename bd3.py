import os
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()  # Carrega variáveis do arquivo .env

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "bot_atendimento"),
}


def get_conn():
    return mysql.connector.connect(**DB_CONFIG, connection_timeout=5)

def criar_atendimento(telefone: str, telefone_bot: str = None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO atendimentos (telefone, telefone_bot, status, atendente_chamado) VALUES (%s, %s, %s, %s)",
            (telefone, telefone_bot, 'em_atendimento', 0)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        cur.close()
        conn.close()

def atualizar_atendimento(atendimento_id: int, **campos):
    if not campos:
        return
    
    colunas = []
    valores = []
    for k, v in campos.items():
        colunas.append(f"{k}=%s")
        valores.append(v)

    valores.append(atendimento_id)

    sql = f"UPDATE atendimentos SET {', '.join(colunas)} WHERE id=%s"

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, tuple(valores))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def marcar_handoff(atendimento_id: int):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE atendimentos SET status=%s, atendente_chamado=%s WHERE id=%s",
            ("handoff", 1, atendimento_id)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

def obter_status_atendimento(atendimento_id: int) -> str:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT status FROM atendimentos WHERE id=%s", (atendimento_id,))
        row = cur.fetchone()
        return row[0] if row else ""
    finally:
        cur.close()
        conn.close()

def finalizar(atendimento_id: int):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE atendimentos SET status=%s, data_fim=NOW() WHERE id=%s",
            ("finalizado", atendimento_id)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

def registrar_evento(atendimento_id: int, tipo_evento: str, valor=None, external_message_id: str = None):
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO atendimento_eventos (atendimento_id, tipo_evento, valor, external_message_id)
            VALUES (%s, %s, %s, %s)
            """,
            (atendimento_id, tipo_evento, valor, external_message_id)
        )
        conn.commit()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()

def listar_fila_handoff(limit=50):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, telefone, nome, matricula, menu_id, sub_id, sub_sub_id, data_inicio, status
              FROM atendimentos
             WHERE status='handoff' AND atendente_chamado=1
             ORDER BY data_inicio ASC
             LIMIT %s
        """, (limit,))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def assumir_atendimento(atendimento_id: int, atendente_nome: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE atendimentos
               SET status='em_atendimento_humano',
                   atendente_nome=%s,
                   assumido_em=NOW()
             WHERE id=%s AND status='handoff'
        """, (atendente_nome, atendimento_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
        conn.close()

def obter_sessao(telefone: str):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM sessao_usuario WHERE telefone=%s", (telefone,))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()

def salvar_sessao(
    telefone: str,
    atendimento_id: int,
    etapa: str,
    ultimo_contato,
    nome=None,
    matricula=None,
    menu_id=None,
    sub_id=None,
    sub_sub_id=None,
    atendente_chamado=0,
    resumo_handoff_salvo=0,
    telefone_bot=None
):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO sessao_usuario
              (telefone, telefone_bot, atendimento_id, etapa, nome, matricula, menu_id, sub_id, sub_sub_id, atendente_chamado, resumo_handoff_salvo, ultimo_contato)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              telefone_bot=VALUES(telefone_bot),
              atendimento_id=VALUES(atendimento_id),
              etapa=VALUES(etapa),
              nome=VALUES(nome),
              matricula=VALUES(matricula),
              menu_id=VALUES(menu_id),
              sub_id=VALUES(sub_id),
              sub_sub_id=VALUES(sub_sub_id),
              atendente_chamado=VALUES(atendente_chamado),
              resumo_handoff_salvo=VALUES(resumo_handoff_salvo),
              ultimo_contato=VALUES(ultimo_contato)
        """, (telefone, telefone_bot, atendimento_id, etapa, nome, matricula, menu_id, sub_id, sub_sub_id, atendente_chamado, resumo_handoff_salvo, ultimo_contato))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def apagar_sessao(telefone: str):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM sessao_usuario WHERE telefone=%s", (telefone,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def validar_login(usuario: str, senha: str) -> bool:
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM atendentes WHERE usuario=%s AND senha=%s", (usuario, senha))
        user = cur.fetchone()
        # Se achou alguém, retorna True. Se não, retorna False.
        return user is not None
    finally:
        cur.close()
        conn.close()
