import json
import threading
from datetime import datetime
from bd3 import get_conn
from fila_disparos import executar_disparo, reenviar_erros
import os
from dotenv import load_dotenv
import pymysql
load_dotenv()

NUMERO_ID_DISPAROS = os.getenv("WA_PHONE_NUMBER_ID_DISPAROS")

def criar_disparo(nome_campanha: str, template_nome: str, numero_id: str, contatos: list) -> int:
    """
    Cria um novo disparo no banco e insere os contatos.

    Args:
        nome_campanha: nome dado ao disparo (ex: "Processo Seletivo Maio")
        template_nome: nome exato do template aprovado na Meta
        numero_id: phone_number_id do número remetente
        contatos: lista de dicts com keys: nome, telefone, variaveis_json

    Returns:
        ID do disparo criado
    """
    if not numero_id:
        numero_id = NUMERO_ID_DISPAROS
        
    conn = get_conn()
    cur = conn.cursor()
    try:
        # Cria o registro do disparo
        cur.execute("""
            INSERT INTO disparos (numero_id, nome_campanha, template_nome, total_contatos, status)
            VALUES (%s, %s, %s, %s, 'ativo')
        """, (numero_id, nome_campanha, template_nome, len(contatos)))
        disparo_id = cur.lastrowid
        conn.commit()

        # Insere os contatos
        for contato in contatos:
            variaveis = contato.get("variaveis_json", {})
            if isinstance(variaveis, dict):
                variaveis = json.dumps(variaveis, ensure_ascii=False)

            cur.execute("""
                INSERT INTO disparos_contatos
                    (disparo_id, nome, telefone, variaveis_json, status)
                VALUES (%s, %s, %s, %s, 'pendente')
            """, (
                disparo_id,
                contato["nome"],
                contato["telefone"],
                variaveis
            ))

        conn.commit()
        print(f"✅ Disparo {disparo_id} criado com {len(contatos)} contatos.")
        return disparo_id

    finally:
        cur.close()
        conn.close()

def iniciar_disparo(disparo_id: int, template_nome: str, numero_id: str = None):
    """
    Inicia o disparo em uma thread separada para não travar o painel.

    Args:
        disparo_id: ID do disparo
        template_nome: nome do template
        numero_id: phone_number_id (opcional)
    """
    thread = threading.Thread(
        target=executar_disparo,
        args=(disparo_id, template_nome, numero_id),
        daemon=True
    )
    thread.start()
    print(f"🚀 Disparo {disparo_id} iniciado em background.")

def pausar_disparo(disparo_id: int):
    """Pausa um disparo em andamento."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE disparos SET status = 'pausado' WHERE id = %s AND status = 'ativo'
        """, (disparo_id,))
        conn.commit()
        alterado = cur.rowcount > 0
        if alterado:
            print(f"⏸️ Disparo {disparo_id} pausado.")
        return alterado
    finally:
        cur.close()
        conn.close()

def retomar_disparo(disparo_id: int, template_nome: str, numero_id: str = None):
    """Retoma um disparo pausado de onde parou."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE disparos SET status = 'ativo' WHERE id = %s AND status = 'pausado'
        """, (disparo_id,))
        conn.commit()
        alterado = cur.rowcount > 0
    finally:
        cur.close()
        conn.close()

    if alterado:
        print(f"▶️ Retomando disparo {disparo_id}...")
        iniciar_disparo(disparo_id, template_nome, numero_id)

    return alterado

def iniciar_reenvio_erros(disparo_id: int, template_nome: str, numero_id: str = None):
    """Reenvia apenas os contatos com erro em background."""
    thread = threading.Thread(
        target=reenviar_erros,
        args=(disparo_id, template_nome, numero_id),
        daemon=True
    )
    thread.start()
    print(f"🔁 Reenvio de erros do disparo {disparo_id} iniciado.")

def listar_disparos() -> list:
    """Lista todos os disparos com resumo de status."""
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute("""
            SELECT
                id,
                nome_campanha,
                template_nome,
                total_contatos,
                enviados,
                erros,
                status,
                data_criacao
            FROM disparos
            ORDER BY data_criacao DESC
        """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def detalhar_disparo(disparo_id: int) -> dict:
    """Retorna detalhes completos de um disparo incluindo contatos."""
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute("""
            SELECT * FROM disparos WHERE id = %s
        """, (disparo_id,))
        disparo = cur.fetchone()

        if not disparo:
            return {}

        cur.execute("""
            SELECT id, nome, telefone, status, erro_msg, tentativas, data_envio
            FROM disparos_contatos
            WHERE disparo_id = %s
            ORDER BY id ASC
        """, (disparo_id,))
        disparo["contatos"] = cur.fetchall()

        contatos = disparo["contatos"]

        total = len(contatos)
        
        enviados = sum(1 for c in contatos if c["status"] == "enviado")
        entregues = sum(1 for c in contatos if c["status"] == "entregue")
        lidos = sum(1 for c in contatos if c["status"] == "lido")
        erros = sum(1 for c in contatos if c["status"] == "erro")
        
        sucessos = enviados + entregues + lidos
        
        taxa_sucesso = round(
            (sucessos / total) * 100,
            2
        ) if total > 0 else 0
        
        disparo["resumo"] = {
            "total": total,
            "enviados": enviados,
            "entregues": entregues,
            "lidos": lidos,
            "erros": erros,
            "taxa_sucesso": taxa_sucesso
        }

        return disparo
    finally:
        cur.close()
        conn.close()

def listar_respostas(disparo_id: int = None) -> list:
    """
    Lista respostas recebidas dos candidatos.
    Se disparo_id for informado, filtra por campanha.
    """
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        if disparo_id:
            cur.execute("""
                SELECT
                    dc.nome,
                    dc.telefone,
                    dc.status,
                    dc.data_status_update,
                    d.nome_campanha,
                    d.template_nome
                FROM disparos_contatos dc
                JOIN disparos d ON dc.disparo_id = d.id
                WHERE dc.disparo_id = %s
                ORDER BY dc.data_status_update DESC
            """, (disparo_id,))
        else:
            cur.execute("""
                SELECT
                    dc.nome,
                    dc.telefone,
                    dc.status,
                    dc.data_status_update,
                    d.nome_campanha,
                    d.template_nome
                FROM disparos_contatos dc
                JOIN disparos d ON dc.disparo_id = d.id
                ORDER BY dc.data_status_update DESC
                LIMIT 200
            """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()
