import os
import mysql.connector
from mysql.connector import pooling, Error
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from utils_tempo import em_horario_comercial, get_tipo_periodo

load_dotenv()  # Carrega variáveis do arquivo .env

DB_CONFIG = {
    "host": os.getenv("DB_HOST", ""),
    "port": int(os.getenv("DB_PORT", "")),
    "user": os.getenv("DB_USER", ""),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", ""),
}

try:
    db_pool = pooling.MySQLConnectionPool(
        pool_size=32, # Aumentado para suportar picos de concorrência (Escalabilidade)
        pool_name="comlurb_pool",
        pool_reset_session=True,
        connect_timeout=5,
        **DB_CONFIG
    )
    print("✅ Pool de banco de dados iniciado com sucesso.")
except Error as e:
    print(f"❌ ERRO CRÍTICO ao criar o pool de conexões: {e}")
    raise

# Warm-up do pool (abre conexões antes do primeiro usuário)
for _ in range(5):
    conn = db_pool.get_connection()
    conn.close()

def get_conn():
    """Pega uma conexão já aberta do Pool instantaneamente."""
    try:
        return db_pool.get_connection()
    except Error as e:
        print(f"❌ Erro ao obter conexão do pool: {e}")
        raise

def criar_atendimento(telefone: str, telefone_bot: str = None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    try:
        agora = datetime.now()
        tipo_periodo = get_tipo_periodo(agora)

        cur.execute(
            """
            INSERT INTO atendimentos 
            (telefone, telefone_bot, status, atendente_chamado, data_inicio, tipo_periodo)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (telefone, telefone_bot, 'em_atendimento', 0, agora, tipo_periodo)
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
    # Busca do .env, se não existir, usa uma data muito antiga para não quebrar nada
    data_corte = os.getenv("DATA_CORTE_PRODUCAO", "2000-01-01 00:00:00")
    try:
        cur.execute("""
            SELECT id, telefone, nome, matricula, menu_id, sub_id, sub_sub_id, data_inicio, status
            FROM atendimentos
            WHERE status IN ('handoff', 'em_atendimento_humano')
            AND atendente_chamado = 1
            AND data_inicio >= %s
            ORDER BY data_inicio ASC
            LIMIT %s
        """, (data_corte, limit))
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

def validar_login(usuario_digitado, senha_digitada):
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT senha FROM atendentes WHERE usuario = %s", (usuario_digitado,))
        resultado = cursor.fetchone()
        
        if resultado:
            senha_banco_hasheada = resultado['senha']
            # Isso compara a senha digitada em texto com o hash embaralhado do banco
            if check_password_hash(senha_banco_hasheada, senha_digitada):
                return True
                
        return False
        
    except Exception as e:
        print("Erro crítico ao validar login no banco de dados:", e)
        return False
        
    finally:
        cursor.close()
        conn.close()
        
def contar_fila_espera_humana() -> int:
    """Conta quantas pessoas estão aguardando na fila de atendimento humano."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        # Conta todos que estão com status 'aguardando'
        cur.execute("SELECT COUNT(*) FROM atendimentos WHERE status = 'aguardando'")
        row = cur.fetchone()
        return row[0] if row else 0
    except Exception as e:
        print(f"❌ Erro ao contar fila de espera: {e}")
        return 0
    finally:
        cur.close()
        conn.close()
