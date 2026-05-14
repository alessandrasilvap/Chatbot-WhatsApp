import pymysql
import os
import time
from datetime import datetime
import requests
from dotenv import load_dotenv
from bd3 import get_conn, finalizar, registrar_evento, apagar_sessao

load_dotenv()

WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_API_VERSION = os.getenv("WA_API_VERSION", "v24.0")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
TIMEOUT_MINUTOS = 10

def enviar_mensagem_whatsapp(telefone_destino, texto):
    """Função genérica e reaproveitável para enviar mensagens via Graph API"""
    url = f"https://graph.facebook.com/{WA_API_VERSION}/{WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": telefone_destino,
        "type": "text",
        "text": {"body": texto}
    }
    try:
        resposta = requests.post(url, headers=headers, json=payload, timeout=10)
        if resposta.status_code != 200:
            print(f"❌ Erro da API da Meta: {resposta.status_code} - {resposta.text}")
    except Exception as e:
        print(f"❌ Erro de rede ao enviar mensagem para {telefone_destino}: {e}")

def varrer_inativos():
    """Varre inativos que estão nos menus do bot. Ignora quem está na fila (aguardando) ou com atendente."""
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        # Pega inativos que NÃO estão aguardando e NÃO estão em atendimento humano
        cur.execute("""
            SELECT s.telefone, s.atendimento_id 
            FROM sessao_usuario s
            INNER JOIN atendimentos a ON s.atendimento_id = a.id
            WHERE s.ultimo_contato <= NOW() - INTERVAL %s MINUTE
              AND a.status NOT IN ('aguardando', 'em_atendimento_humano')
        """, (TIMEOUT_MINUTOS,))
        
        inativos = cur.fetchall()

        for sessao in inativos:
            telefone = sessao['telefone']
            atendimento_id = sessao['atendimento_id']

            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧹 Encerrando sessão inativa: {telefone}")
            
            texto_timeout = (
                "⏱️ *Atendimento encerrado por inatividade.*\n\n"
                "Como não tivemos resposta nos últimos 10 minutos, encerramos esta sessão. "
                "Se precisar de ajuda novamente, envie uma nova mensagem."
            )
            enviar_mensagem_whatsapp(telefone, texto_timeout)
            
            registrar_evento(atendimento_id, "timeout_finalizado", "Worker Inatividade")
            finalizar(atendimento_id)
            apagar_sessao(telefone)

    except Exception as e:
        print(f"❌ Erro ao varrer inativos: {e}")
    finally:
        cur.close()
        conn.close()

def limpar_fila_fim_expediente():
    """Roda às 17h para limpar a fila de quem não foi atendido."""
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        # Busca quem está com status 'aguardando'
        cur.execute("""
            SELECT s.telefone, s.atendimento_id 
            FROM sessao_usuario s
            INNER JOIN atendimentos a ON s.atendimento_id = a.id
            WHERE a.status = 'aguardando'
        """)
        abandonados = cur.fetchall()

        for sessao in abandonados:
            telefone = sessao['telefone']
            atendimento_id = sessao['atendimento_id']
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🏢 Limpando fila (Fim de expediente): {telefone}")
            
            texto_fim_expediente = (
                "Pedimos desculpas, mas nosso expediente encerrou e não conseguimos "
                "conectar você a um atendente a tempo.\n\n"
                "🕒 Nosso horário é de *Segunda a Sexta, das 08h às 17h*.\n"
                "Por favor, retorne o contato dentro deste horário no próximo dia útil para falarmos com você!"
            )
            enviar_mensagem_whatsapp(telefone, texto_fim_expediente)
            
            registrar_evento(atendimento_id, "expediente_encerrado_na_fila", "Worker Horário")
            finalizar(atendimento_id)
            apagar_sessao(telefone)
            
    except Exception as e:
        print(f"❌ Erro ao limpar fila no fim do expediente: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    print("🚀 Worker Automático iniciado! Monitorando inatividade e horário comercial...")
    
    ultima_limpeza = None  # Guarda a DATA da última limpeza, não só True/False

    while True:
        agora = datetime.now()
        
        # Rotina de Inatividade (roda sempre a cada minuto)
        varrer_inativos()
        
        # Rotina de Fim de Expediente (roda só às 17:01, dias de semana)
        # Compara a DATA de hoje com a data da última limpeza
        # Mesmo que o worker reinicie, não vai rodar duas vezes no mesmo dia
        if agora.weekday() < 5 and agora.hour == 17 and agora.minute == 1:
            if ultima_limpeza != agora.date():
                limpar_fila_fim_expediente()
                ultima_limpeza = agora.date()
                print(f"✅ Limpeza de fim de expediente concluída em {ultima_limpeza}")
    
        time.sleep(60)
