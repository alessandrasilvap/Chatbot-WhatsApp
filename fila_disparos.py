import time
import json
from datetime import datetime
from bd3 import get_conn
import pymysql
from envio_whatsapp import enviar_template

# Delay entre cada mensagem (em segundos) — evita bloqueio da Meta
DELAY_ENTRE_MENSAGENS = 2

def buscar_contatos_pendentes(disparo_id: int) -> list:
    """Busca todos os contatos com status pendente de um disparo."""
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute("""
            SELECT id, nome, telefone, variaveis_json
            FROM disparos_contatos
            WHERE disparo_id = %s AND status = 'pendente'
        """, (disparo_id,))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def atualizar_status_contato(contato_id: int, status: str, wamid: str = None, erro_msg: str = None):
    """Atualiza o status de um contato individual."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE disparos_contatos
            SET status = %s,
                wamid = %s,
                erro_msg = %s,
                data_envio = %s,
                data_status_update = %s,
                tentativas = tentativas + 1
            WHERE id = %s
        """, (status, wamid, erro_msg, datetime.now(), datetime.now(), contato_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def atualizar_contadores_disparo(disparo_id: int):
    """Recalcula enviados e erros do disparo com base nos contatos."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE disparos d
            SET
                enviados = (
                    SELECT COUNT(*) FROM disparos_contatos
                    WHERE disparo_id = %s AND status IN ('enviado', 'entregue', 'lido')
                ),
                erros = (
                    SELECT COUNT(*) FROM disparos_contatos
                    WHERE disparo_id = %s AND status = 'erro'
                )
            WHERE id = %s
        """, (disparo_id, disparo_id, disparo_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def verificar_status_disparo(disparo_id: int) -> str:
    """Verifica se o disparo está ativo, pausado ou finalizado."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT status FROM disparos WHERE id = %s", (disparo_id,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        cur.close()
        conn.close()

def finalizar_disparo(disparo_id: int):
    """Marca o disparo como finalizado."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE disparos SET status = 'finalizado' WHERE id = %s
        """, (disparo_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def executar_disparo(disparo_id: int, template_nome: str, numero_id: str = None):
    """
    Executa o disparo de mensagens para todos os contatos pendentes.
    Respeita pausas e delays entre mensagens.
    
    Args:
        disparo_id: ID do disparo na tabela disparos
        template_nome: nome exato do template aprovado na Meta
        numero_id: phone_number_id
    """
    print(f"🚀 Iniciando disparo ID {disparo_id}...")

    contatos = buscar_contatos_pendentes(disparo_id)

    if not contatos:
        print("⚠️ Nenhum contato pendente encontrado.")
        finalizar_disparo(disparo_id)
        return

    for contato in contatos:
        # Verifica se o disparo foi pausado ou finalizado antes de cada envio
        status_atual = verificar_status_disparo(disparo_id)

        if status_atual == 'pausado':
            print(f"⏸️ Disparo {disparo_id} pausado. Parando fila.")
            return

        if status_atual == 'finalizado':
            print(f"🏁 Disparo {disparo_id} já finalizado.")
            return

        # Monta as variáveis do template
        variaveis_raw = contato.get("variaveis_json")
        if isinstance(variaveis_raw, str):
            variaveis_dict = json.loads(variaveis_raw)
        else:
            variaveis_dict = variaveis_raw or {}

        variaveis_lista = list(variaveis_dict.values())

        # Formata o telefone (garante que tem DDI 55)
        telefone = contato["telefone"].strip().replace(" ", "").replace("-", "")
        if not telefone.startswith("55"):
            telefone = "55" + telefone

        print(f"📤 Enviando para {contato['nome']} ({telefone})...")

        resultado = enviar_template(
            telefone=telefone,
            template_nome=template_nome,
            variaveis=variaveis_lista,
            numero_id=numero_id
        )

        if resultado["sucesso"]:
            atualizar_status_contato(
                contato_id=contato["id"],
                status="enviado",
                wamid=resultado["wamid"]
            )
            print(f"✅ Enviado com sucesso! wamid: {resultado['wamid']}")
        else:
            atualizar_status_contato(
                contato_id=contato["id"],
                status="erro",
                erro_msg=resultado["erro"]
            )
            print(f"❌ Erro ao enviar: {resultado['erro']}")

        # Atualiza os contadores do disparo a cada envio
        atualizar_contadores_disparo(disparo_id)

        # Delay entre mensagens para não ser bloqueado
        time.sleep(DELAY_ENTRE_MENSAGENS)

    # Finaliza o disparo após enviar todos
    finalizar_disparo(disparo_id)
    print(f"🏁 Disparo {disparo_id} finalizado!")

def reenviar_erros(disparo_id: int, template_nome: str, numero_id: str = None):
    """
    Reseta os contatos com erro para pendente e reinicia o disparo.
    
    Args:
        disparo_id: ID do disparo
        template_nome: nome do template
        numero_id: phone_number_id (opcional)
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE disparos_contatos
            SET status = 'pendente', erro_msg = NULL
            WHERE disparo_id = %s AND status = 'erro'
        """, (disparo_id,))
        conn.commit()
        print(f"🔁 Contatos com erro resetados para pendente.")
    finally:
        cur.close()
        conn.close()

    # Reativa o disparo e executa novamente
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE disparos SET status = 'ativo' WHERE id = %s", (disparo_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    executar_disparo(disparo_id, template_nome, numero_id)
