import os
import time
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv
from bd3 import get_conn, finalizar, registrar_evento, apagar_sessao

load_dotenv()

WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_API_VERSION = os.getenv("WA_API_VERSION", "v24.0")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
TIMEOUT_MINUTOS = 10

def enviar_mensagem_timeout(telefone_destino, telefone_bot_origem):
    # O bot que envia a mensagem é o que estava atendendo o cliente
    sender_id = telefone_bot_origem if telefone_bot_origem else WA_PHONE_NUMBER_ID
    
    url = f"https://graph.facebook.com/{WA_API_VERSION}/{sender_id}/messages"
    headers = {
        "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    texto = (
        "⏱️ *Atendimento encerrado por inatividade.*\n\n"
        "Como não tivemos resposta nos últimos 10 minutos, finalizamos esta sessão para liberar a fila. "
        "Se precisar de ajuda novamente, envie uma nova mensagem para iniciar um novo atendimento."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": telefone_destino,
        "type": "text",
        "text": {"body": texto}
    }
    
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Erro de rede ao enviar timeout para {telefone_destino}: {e}")

def varrer_inativos():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        agora = datetime.now()
        limite_tempo = agora - timedelta(minutes=TIMEOUT_MINUTOS)
        
        # Busca todo mundo que passou de 10 minutos sem falar nada
        cur.execute("""
            SELECT telefone, atendimento_id, telefone_bot 
            FROM sessao_usuario 
            WHERE ultimo_contato < %s
        """, (limite_tempo,))
        
        inativos = cur.fetchall()

        for sessao in inativos:
            telefone = sessao['telefone']
            atendimento_id = sessao['atendimento_id']
            telefone_bot = sessao['telefone_bot']

            print(f"[{agora.strftime('%H:%M:%S')}] 🧹 Encerrando sessão inativa: {telefone}")

            # 1. Avisa o cliente pelo WhatsApp Oficial
            enviar_mensagem_timeout(telefone, telefone_bot)

            # 2. Registra e apaga do banco de dados
            registrar_evento(atendimento_id, "timeout_finalizado", "Worker Automático")
            finalizar(atendimento_id)
            apagar_sessao(telefone)

    except Exception as e:
        print(f"❌ Erro ao varrer banco: {e}")
    finally:
        cur.close()
        conn.close() # Devolve a conexão pro Pool!

if __name__ == "__main__":
    print("🚀 Worker de Timeout iniciado e monitorando o banco a cada 60 segundos...")
    while True:
        varrer_inativos()
        time.sleep(60) # Pausa por 1 minuto antes de checar de novo