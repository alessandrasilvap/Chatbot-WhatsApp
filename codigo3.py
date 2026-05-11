from flask import Flask, request, jsonify, session, redirect, render_template
from flask_socketio import SocketIO
from menusSubmenus3 import texto_menu_principal, texto_submenu, texto_sub_submenu, obter_script, texto_opcoes_pos_script
from bd3 import (
    criar_atendimento, atualizar_atendimento, marcar_handoff, finalizar, registrar_evento, assumir_atendimento,
    obter_status_atendimento, obter_sessao, salvar_sessao, apagar_sessao, get_conn, validar_login, contar_fila_espera_humana
)
from disparos import (
    criar_disparo, iniciar_disparo, pausar_disparo,
    retomar_disparo, iniciar_reenvio_erros, listar_disparos, detalhar_disparo, listar_respostas
)
from redis import Redis, ConnectionPool
from rq import Queue
import holidays
from datetime import datetime, timedelta, time
import os
import hmac
import hashlib
import requests
from dotenv import load_dotenv
from functools import wraps
from utils_tempo import em_horario_comercial, get_tipo_periodo

# Carrega variáveis do .env
load_dotenv()

# ============================================================
# CONFIGURAÇÃO DA FILA DE ALTA PERFORMANCE (REDIS + RQ)
# ============================================================
redis_conn = None

try:
    pool = ConnectionPool(
        host='localhost',
        port=6379,
        max_connections=20,
        socket_connect_timeout=5,
        socket_timeout=5
    )
    redis_conn = Redis(connection_pool=pool)
    fila_zap = Queue('fila_zap', connection=redis_conn)

    # Warm-up Redis
    redis_conn.ping()
    print("🔥 Redis aquecido (ping OK)")
except Exception as e:
    print(f"❌ ERRO CRÍTICO ao conectar no Redis: {e}")

# ============================================================
# CACHE DE DEDUPLICAÇÃO (MEMÓRIA ANTI-REPETIÇÃO)
# ============================================================
def is_duplicada_redis(message_id: str, prefix="msg") -> bool:
    if not message_id or not redis_conn:
        return False

    try:
        chave = f"{prefix}:{message_id}"
        foi_criada = redis_conn.set(chave, "1", ex=7200, nx=True)
        return not foi_criada
    except Exception as e:
        print(f"Erro Redis deduplicação: {e}")
        return False

# ============================================================
# APP / ENV
# ============================================================
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "")
WA_APP_SECRET = os.getenv("WA_APP_SECRET", "")  # Pode ficar vazio (modo dev)
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_API_VERSION = os.getenv("WA_API_VERSION", "v24.0")
app.secret_key = ""

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_logado' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_logado' not in session:
            return redirect('/login')
        permissao = session.get('permissao')
        painel = session.get('painel')
        if permissao not in ['admin', 'chat'] and painel != 'chat':
            return "❌ Acesso Negado.", 403
        return f(*args, **kwargs)
    return decorated_function

def disparo_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_logado' not in session:
            return redirect('/login')
        permissao = session.get('permissao')
        painel = session.get('painel')
        if permissao not in ['admin', 'disparo'] and painel != 'disparo':
            return "❌ Acesso Negado.", 403
        return f(*args, **kwargs)
    return decorated_function

def verify_signature(req) -> bool:
    """
    Verifica X-Hub-Signature-256 (sha256=...) com HMAC usando o App Secret.
    Se WA_APP_SECRET estiver vazio, fica em modo dev e aceita.
    """
    if not WA_APP_SECRET:
        return True  # Modo dev

    sig = req.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False

    provided = sig.split("=", 1)[1].strip()
    body = req.get_data()

    expected = hmac.new(
        WA_APP_SECRET.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(provided, expected)

def extract_text_messages(payload: dict):
    """
    Extrai mensagens do webhook. Se não for texto, cria uma tag especial.
    """
    results = []
    for e in payload.get("entry", []) or []:
        for c in (e.get("changes", []) or []):
            value = c.get("value", {}) or {}
            
            metadata = value.get("metadata") or {}
            telefone_bot = str(metadata.get("display_phone_number") or "").strip()
            phone_number_id = str(metadata.get("phone_number_id") or "").strip()
            
            for m in (value.get("messages", []) or []):
                msg_type = m.get("type", "")
                wa_from = str(m.get("from") or "").strip()
                msg_id = str(m.get("id") or "").strip()
                
                # Se for texto, pega o body. Se for mídia, cria a tag interna
                if msg_type == "text":
                    text = str(((m.get("text") or {}).get("body") or "")).strip()
                else:
                    text = f"__MEDIA__{msg_type.upper()}"
                
                if wa_from and text:
                    results.append({
                        "from": wa_from, 
                        "id": msg_id, 
                        "text": text, 
                        "telefone_bot": telefone_bot,
                        "phone_number_id": phone_number_id
                    })
    return results

def extract_status_updates(payload: dict) -> list:
    """
    Extrai atualizações de status (entregue, lido) do webhook da Meta.
    Usado para atualizar o status dos disparos em massa.
    """
    results = []
    for e in payload.get("entry", []) or []:
        for c in (e.get("changes", []) or []):
            value = c.get("value", {}) or {}
            for s in (value.get("statuses", []) or []):
                wamid = s.get("id", "")
                status_meta = s.get("status", "")  # sent, delivered, read, failed

                # Mapeia status da Meta para o nosso banco
                mapa = {
                    "sent": "enviado",
                    "delivered": "entregue",
                    "read": "lido",
                    "failed": "erro"
                }
                status_bd = mapa.get(status_meta)

                if wamid and status_bd:
                    results.append({"wamid": wamid, "status": status_bd})
    return results


def atualizar_status_por_wamid(wamid: str, status: str):
    """
    Atualiza o status de um contato de disparo pelo wamid.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE disparos_contatos
            SET status = %s, data_status_update = NOW()
            WHERE wamid = %s
        """, (status, wamid))
        conn.commit()
        if cur.rowcount > 0:
            print(f"✅ Status atualizado via webhook: {wamid} → {status}")
    finally:
        cur.close()
        conn.close()

# ============================================================
# WhatsApp SEND (Cloud API) - COM MONITORIZAÇÃO DE ERROS
# ============================================================
def send_whatsapp_text(to_wa_id: str, text: str, phone_number_id: str = None) -> bool:
    if not WA_ACCESS_TOKEN:
        print("❌ WA_ACCESS_TOKEN vazio no .env.")
        return False

    # Se vier um ID específico (do webhook), usa-o. Se não vier, usa o padrão do .env
    sender_id = phone_number_id if phone_number_id else WA_PHONE_NUMBER_ID
    
    if not sender_id:
        print("❌ Nenhum phone_number_id configurado para envio.")
        return False

    url = f"https://graph.facebook.com/{WA_API_VERSION}/{sender_id}/messages"
    headers = {
        "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": text}
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        
        # Se a Meta devolver um código de erro (400, 401, 403, etc.)
        if r.status_code >= 300:
            erro_json = r.json().get("error", {})
            codigo_erro = erro_json.get("code", "N/A")
            mensagem_erro = erro_json.get("message", r.text)
            
            print(f"❌ [ERRO META {codigo_erro}] Falha ao enviar para {to_wa_id}: {mensagem_erro}")
            
            # Tenta registar o erro diretamente na base de dados do atendimento atual
            try:
                from bd3 import obter_sessao, registrar_evento
                sessao = obter_sessao(to_wa_id)
                if sessao and sessao.get("atendimento_id"):
                    # Grava o erro no histórico do cliente para o painel HTML ver depois!
                    registrar_evento(sessao["atendimento_id"], "erro_envio_meta", f"Cod {codigo_erro}: {mensagem_erro}")
            except Exception as bd_err:
                print("❌ Erro ao tentar guardar o registo de falha na base de dados:", bd_err)
                
            return False
            
        else:
            print("✅ WhatsApp enviado para", to_wa_id, "pelo ID", sender_id)
            return True
            
    except Exception as e:
        print("❌ Exceção crítica de rede ao enviar WhatsApp:", e)
        return False

# ============================================================
# CORE handler (motor do bot)
# Agora retorna TEXTO (string), não jsonify.
# ============================================================
def handle_incoming(telefone: str, mensagem: str, agora: datetime, message_id: str = None, telefone_bot: str = None) -> str:

    if not telefone:
        return "❌ Erro: telefone não informado."

    sessao = obter_sessao(telefone)

    # Primeiro cria o atendimento
    if not sessao:
        atendimento_id = criar_atendimento(telefone, telefone_bot)

        registrar_evento(atendimento_id, "inicio_atendimento")

        # DEDUPE
        if message_id:
            try:
                registrar_evento(atendimento_id, "msg_usuario", mensagem, external_message_id=message_id)
            except Exception as e:
                if "duplicate" in str(e).lower():
                    return "✅ (dedupe-db) mensagem já processada"
                raise
        else:
            registrar_evento(atendimento_id, "msg_usuario", mensagem)

        salvar_sessao(
            telefone=telefone,
            atendimento_id=atendimento_id,
            etapa="nome",
            ultimo_contato=agora,
            telefone_bot=telefone_bot
        )

        # Offline (depois de salvar)
        if not em_horario_comercial(agora):
            finalizar(atendimento_id)
            apagar_sessao(telefone)
            
            return (
                "⏰ *Nosso atendimento está offline no momento.*\n\n"
                "Funcionamos de segunda a sexta, das 08:00 às 17:00 (exceto feriados).\n"
                "Por favor, envie sua mensagem novamente dentro desse período."
            )

        return (
            "Olá! 👋 Sou a assistente virtual do Canal I da COMLURB.\n\n"
            "Estou aqui para ajudar a tirar suas dúvidas de forma rápida. Mas não se preocupe: se precisar, você poderá escolher falar com um atendente da equipe do Canal I.\n\n"
            "⚠️ *Aviso:* Para agilizar o atendimento de todos, conversas sem interação por mias de 10 minutos são encerradas automaticamente.\n\n"
            "Para começarmos, digite o seu *nome*."
        )

    atendimento_id = sessao["atendimento_id"]

    # DEDUPE + REGISTRO
    if message_id:
        try:
            registrar_evento(atendimento_id, "msg_usuario", mensagem, external_message_id=message_id)
        except Exception as e:
            if "duplicate" in str(e).lower():
                return "✅ (dedupe-db) mensagem já processada"
            raise
    else:
        registrar_evento(atendimento_id, "msg_usuario", mensagem)

    # Atualiza sessão
    salvar_sessao(
        telefone=telefone,
        atendimento_id=atendimento_id,
        etapa=sessao["etapa"],
        ultimo_contato=agora,
        nome=sessao.get("nome"),
        matricula=sessao.get("matricula"),
        menu_id=sessao.get("menu_id"),
        sub_id=sessao.get("sub_id"),
        atendente_chamado=sessao.get("atendente_chamado", 0),
        resumo_handoff_salvo=sessao.get("resumo_handoff_salvo", 0),
        telefone_bot=telefone_bot
    )

    # Humano assumiu
    status_bd = obter_status_atendimento(atendimento_id)

    if status_bd == "em_atendimento_humano":

        if mensagem == "3":
            registrar_evento(atendimento_id, "finalizar")
            finalizar(atendimento_id)
            apagar_sessao(telefone)
            return "✅ Atendimento finalizado."

        # Mídia durante atendimento humano
        if mensagem.startswith("__MEDIA__"):
            aviso = "⚠️ [SISTEMA: cliente enviou mídia]"
            registrar_evento(atendimento_id, "msg_usuario", aviso)
            return ""

        return ""

    # Mídia durante atendimento bot
    if mensagem.startswith("__MEDIA__"):
        return (
            "❌ *Formato não suportado.*\n\n"
            "Envie sua mensagem em texto para continuar."
        )

    # Offline (depois de salvar)
    if not em_horario_comercial(agora):
        finalizar(atendimento_id)
        apagar_sessao(telefone)
        
        return (
            "⏰ *Nosso atendimento está offline no momento.*\n\n"
            "Funcionamos de segunda a sexta, das 08:00 às 17:00 (exceto feriados).\n"
            "Por favor, envie sua mensagem novamente dentro desse período."
        )

    etapa = sessao["etapa"]

    if etapa == "nome":
        if not mensagem:
            return "❌ Por favor, informe seu *nome*."

        nome = mensagem
        atualizar_atendimento(atendimento_id, nome=nome)
        registrar_evento(atendimento_id, "informou_nome", nome)

        salvar_sessao(
            telefone=telefone,
            atendimento_id=atendimento_id,
            etapa="matricula",
            ultimo_contato=agora,
            nome=nome,
            telefone_bot=telefone_bot
        )

        return f"Obrigada, {nome}! 😊 Agora, informe sua *matrícula* (apenas números)."

    if etapa == "matricula":
        if not mensagem.isdigit():
            return "❌ Matrícula inválida."

        matricula = mensagem
        atualizar_atendimento(atendimento_id, matricula=matricula)
        registrar_evento(atendimento_id, "informou_matricula", matricula)

        salvar_sessao(
            telefone=telefone,
            atendimento_id=atendimento_id,
            etapa="menu_principal",
            ultimo_contato=agora,
            telefone_bot=telefone_bot
        )

        return "Cadastro realizado ✅\n\n" + texto_menu_principal()
        
    # Etapa: menu principal
    if etapa == "menu_principal":
        opcoes_validas = [str(i) for i in range(1, 11)]
        if mensagem not in opcoes_validas:
            return "❌ Opção inválida.\n\n" + texto_menu_principal()

        menu_id = mensagem
        atualizar_atendimento(atendimento_id, menu_id=menu_id)
        registrar_evento(atendimento_id, "menu_escolhido", menu_id)

        salvar_sessao(
            telefone=telefone,
            atendimento_id=atendimento_id,
            etapa="submenu",
            ultimo_contato=agora,
            nome=sessao.get("nome"),
            matricula=sessao.get("matricula"),
            menu_id=menu_id,
            sub_id=None,
            atendente_chamado=sessao.get("atendente_chamado", 0),
            resumo_handoff_salvo=sessao.get("resumo_handoff_salvo", 0),
            telefone_bot=telefone_bot
        )
        return texto_submenu(menu_id)

    # Etapa: submenu
    if etapa == "submenu":
        menu_id = sessao.get("menu_id")
        sub_id = mensagem

        if not sub_id.isdigit():
            return f"❌ Opção inválida. Digite apenas o número:\n\n{texto_submenu(menu_id)}"

        # Lógica do botão voltar
        if sub_id == "0":
            registrar_evento(atendimento_id, "voltar_menu_principal")
            salvar_sessao(
                telefone=telefone, atendimento_id=atendimento_id,
                etapa="menu_principal", ultimo_contato=agora,
                nome=sessao.get("nome"), matricula=sessao.get("matricula"),
                menu_id=None, sub_id=None, # Limpa as escolhas
                telefone_bot=telefone_bot
            )
            return texto_menu_principal()

        script_teste = obter_script(menu_id, sub_id, "1") # Tenta o primeiro item
        if not script_teste and sub_id != "0":
             # Se não achou nada, é porque o número digitado não existe para este menu
             return f"❌ Opção inválida.\n\n{texto_submenu(menu_id)}"
        
        registrar_evento(atendimento_id, "submenu_escolhido", f"{menu_id}:{sub_id}")
        atualizar_atendimento(atendimento_id, sub_id=sub_id)

        # Para os menus de 1 a 10
        salvar_sessao(
            telefone=telefone,
            atendimento_id=atendimento_id,
            etapa="sub_submenu",
            ultimo_contato=agora,
            nome=sessao.get("nome"),
            matricula=sessao.get("matricula"),
            menu_id=menu_id,
            sub_id=sub_id,
            atendente_chamado=sessao.get("atendente_chamado", 0),
            resumo_handoff_salvo=sessao.get("resumo_handoff_salvo", 0),
            telefone_bot=telefone_bot
        )
        return texto_sub_submenu(menu_id, sub_id)

    # Etapa sub_submenu
    if etapa == "sub_submenu":
        menu_id = sessao.get("menu_id")
        sub_id = sessao.get("sub_id")
        sub_sub_id = mensagem

        if not sub_sub_id.isdigit():
            return f"❌ Opção inválida. Digite apenas o número:\n\n{texto_sub_submenu(menu_id, sub_id)}"

        if sub_sub_id == "0":
            registrar_evento(atendimento_id, "voltar_submenu")
            salvar_sessao(
                telefone=telefone, atendimento_id=atendimento_id,
                etapa="submenu", ultimo_contato=agora,
                nome=sessao.get("nome"), matricula=sessao.get("matricula"),
                menu_id=menu_id, sub_id=None, # Mantém o menu principal, limpa o submenu
                telefone_bot=telefone_bot
            )
            return texto_submenu(menu_id)

        registrar_evento(atendimento_id, "sub_submenu_escolhido", f"{menu_id}:{sub_id}:{sub_sub_id}")

        # Vai procurar a resposta passando as 3 chaves
        script = obter_script(menu_id, sub_id, sub_sub_id)

        if not script:
            registrar_evento(atendimento_id, "erro_digitacao", f"Input invalido: {sub_sub_id}")
            return f"❌ Opção inválida.\n\n{texto_sub_submenu(menu_id, sub_id)}"

        # Se a resposta for a palavra mágica, chama o humano
        if script == "HANDOFF":
            marcar_handoff(atendimento_id)
            registrar_evento(atendimento_id, "handoff")
            salvar_sessao(
                telefone=telefone, atendimento_id=atendimento_id,
                etapa="handoff", ultimo_contato=agora,
                nome=sessao.get("nome"), matricula=sessao.get("matricula"),
                menu_id=menu_id, sub_id=sub_id, atendente_chamado=1, resumo_handoff_salvo=0,
                telefone_bot=telefone_bot
            )
            return "📞 Ok! Um atendente da equipe do Canal I foi acionado.\n\n📌 Antes, diga-me em *1 frase* o que precisa."

        # Se for uma resposta normal de texto
        atualizar_atendimento(atendimento_id, resposta_bot=script)

        salvar_sessao(
            telefone=telefone, atendimento_id=atendimento_id,
            etapa="pos_resposta", ultimo_contato=agora,
            nome=sessao.get("nome"), matricula=sessao.get("matricula"),
            menu_id=menu_id, sub_id=sub_id, atendente_chamado=0, resumo_handoff_salvo=0,
            telefone_bot=telefone_bot
        )

        return f"{script}\n{texto_opcoes_pos_script()}"

    # Etapa: pos_resposta
    if etapa == "pos_resposta":
        if mensagem not in ["0", "1", "2"]:
            return f"❌ Opção inválida.\n{texto_opcoes_pos_script()}"

        if mensagem == "1":
            registrar_evento(atendimento_id, "voltar_menu")
            salvar_sessao(
                telefone=telefone,
                atendimento_id=atendimento_id,
                etapa="menu_principal",
                ultimo_contato=agora,
                nome=sessao.get("nome"),
                matricula=sessao.get("matricula"),
                menu_id=None,
                sub_id=None,
                sub_sub_id=None,
                telefone_bot=telefone_bot
            )
            return texto_menu_principal()

        if mensagem == "2":
            registrar_evento(atendimento_id, "finalizar")
            finalizar(atendimento_id)
            apagar_sessao(telefone)
            return "✅ Atendimento finalizado.\n\nO Canal I agradece o seu contato. Se precisar no futuro, é só mandar uma nova mensagem."

        if mensagem == "0":
            registrar_evento(atendimento_id, "voltar_menu_anterior")
            salvar_sessao(
                telefone=telefone,
                atendimento_id=atendimento_id,
                etapa="sub_submenu",
                ultimo_contato=agora,
                nome=sessao.get("nome"),
                matricula=sessao.get("matricula"),
                menu_id=sessao.get("menu_id"),
                sub_id=sessao.get("sub_id"),
                sub_sub_id=None,
                telefone_bot=telefone_bot
            )
            return texto_sub_submenu(sessao.get("menu_id"), sessao.get("sub_id"))

    # Etapa: handoff
    if etapa == "handoff":
        if mensagem == "3":
            registrar_evento(atendimento_id, "finalizar")
            finalizar(atendimento_id)
            apagar_sessao(telefone)
            return "✅ Atendimento finalizado.\n\nO Canal I agradece o seu contato. Se precisar no futuro, é só mandar uma nova mensagem."

        if not sessao.get("resumo_handoff_salvo"):
            registrar_evento(atendimento_id, "resumo_handoff", mensagem)
            atualizar_atendimento(atendimento_id, status="aguardando")
            socketio.emit('fila_atualizada', {})
            
            posicao_fila = contar_fila_espera_humana()
            
            if posicao_fila <= 1:
                msg_espera = (
                    "✅ Sua solicitação foi encaminhada.\n\n"
                    "Você é a **próxima pessoa** da fila. Por favor, aguarde um instante."
                ) 
            else:
                pessoas_na_frente = posicao_fila - 1
                msg_espera = (
                    "✅ Sua solicitação foi encaminhada.\n\n"
                    f"Neste momento, existem **{pessoas_na_frente} pessoa(s)** aguardando na sua frente. "
                    "Agradecemos a paciência e logo nossa equipe falará com você."
                )
            
            salvar_sessao(
                telefone=telefone,
                atendimento_id=atendimento_id,
                etapa="handoff",
                ultimo_contato=agora,
                nome=sessao.get("nome"),
                matricula=sessao.get("matricula"),
                menu_id=sessao.get("menu_id"),
                sub_id=sessao.get("sub_id"),
                atendente_chamado=1,
                resumo_handoff_salvo=1,
                telefone_bot=telefone_bot
            )
            return msg_espera

        return "📞 Você está aguardando um atendente da equipe do Canal I. Se quiser, digite 3 para finalizar."

    return "Algo inesperado aconteceu 😅"

# ============================================================
# ROTAS DO PAINEL WEB
# ============================================================
@app.route('/', methods=['GET'])
@app.route('/login', methods=['GET', 'POST'])
def tela_login():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        senha = request.form.get('senha')
        painel = request.form.get('painel')  # 'chat' ou 'disparo'

        resultado = validar_login(usuario, senha)

        if resultado["autenticado"]:
            permissao = resultado["permissao"]

            # Verifica se tem acesso ao painel escolhido
            tem_acesso = (
                permissao == 'admin' or
                (permissao == 'chat' and painel == 'chat') or
                (permissao == 'disparo' and painel == 'disparo')
            )

            if tem_acesso:
                session['usuario_logado'] = resultado["usuario"]
                session['permissao'] = permissao
                session['painel'] = painel

                if painel == 'disparo':
                    return redirect('/disparos')
                else:
                    return redirect('/admin')
            else:
                return render_template('login.html', erro="⛔ Acesso restrito. Você não tem permissão para este painel.")
        else:
            return render_template('login.html', erro="Usuário ou senha incorretos")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ============================================================
# WEBHOOK META
# ============================================================
def processar_mensagem_background(m):
    """
    Esta função é o 'motor' que a fila chama. 
    Ela recebe a mensagem e executa a lógica do bot.
    """
    with app.app_context():
        try:
            telefone = m.get('from')
            texto = m.get('text')
            msg_id = m.get('id')
            telefone_bot = m.get('telefone_bot')
            phone_number_id = m.get('phone_number_id')
            
            agora = datetime.now()

            # Chama o motor principal (handle_incoming)
            resposta = handle_incoming(
                telefone=telefone, 
                mensagem=texto, 
                agora=agora, 
                message_id=msg_id, 
                telefone_bot=telefone_bot
            )

            # Se o bot decidiu responder algo, envia para o WhatsApp
            if resposta and not is_duplicada_redis(msg_id, "send"):
                    send_whatsapp_text(telefone, resposta, phone_number_id=phone_number_id)
                
        except Exception as e:
            print(f"❌ Erro no processamento em background: {e}")
            
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # A Meta usa GET apenas uma vez para verificar se a URL é sua
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == WA_VERIFY_TOKEN:
            print(">>> META VERIFICOU O WEBHOOK COM SUCESSO!")
            return challenge, 200
        else:
            print("❌ Falha na verificação. Token incorreto.")
            return "Falha na verificacao", 403

    # A Meta usa POST toda vez que um usuário mandar mensagem
    if request.method == "POST":
        print(">>> WEBHOOK CHEGOU: MENSAGEM RECEBIDA!")
        
        if not verify_signature(request):
            print("❌ Assinatura inválida (verify_signature falhou).")
            return "Invalid signature", 403

        payload = request.get_json(silent=True) or {}

        # Processa atualizações de status dos disparos
        status_updates = extract_status_updates(payload)
        for s in status_updates:
            atualizar_status_por_wamid(s["wamid"], s["status"])

        msgs = extract_text_messages(payload)
        print(">>> Mensagens extraidas:", msgs)

        # Joga a mensagem na Fila do Redis instantaneamente
        for m in msgs:
            msg_id = m.get("id")
        
            if is_duplicada_redis(msg_id, "msg"):
                print(f"⚠️ Mensagem duplicada ignorada (Redis): {msg_id}")
                continue
        
            fila_zap.enqueue('codigo3.processar_mensagem_background', m)
            print(f">>> Mensagem de {m.get('from')} enfileirada no Redis com sucesso!")
            
        # O FLASK RETORNA 200 OK IMEDIATAMENTE PARA A META, 
        return "OK", 200

# ============================================================
# ADMIN - BLINDADO COM VERIFICAÇÃO DE SESSÃO
# ============================================================
# Lista de usuários que podem acessar a tela histórico
USUARIOS_ADMIN = ['admin']

@app.route('/admin')
@admin_required
def painel_admin():
    return render_template('painel.html', usuario=session['usuario_logado'])

@app.get("/admin/fila")
@admin_required
def admin_fila():
    try:
        conn = get_conn()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute('''
            SELECT id, telefone, nome, matricula, status, DATE_FORMAT(data_inicio, '%Y-%m-%d %H:%i:%s') as data_inicio
            FROM atendimentos
            WHERE status IN ('aguardando', 'em_atendimento_humano', 'encerrado', 'finalizado')
                AND MONTH(data_inicio) = MONTH(CURRENT_DATE()) 
                AND YEAR(data_inicio) = YEAR(CURRENT_DATE())
            ORDER BY 
                CASE status 
                    WHEN 'aguardando' THEN 1 
                    WHEN 'em_atendimento_humano' THEN 2 
                    ELSE 3 
                END, 
                data_inicio ASC
            LIMIT 100
        ''')
        fila = cursor.fetchall()
        cursor.close()
        conn.close()

        # ==========================================
        # Calculando os contadores no Python
        # ==========================================
        qtd_aguardando = sum(1 for a in fila if a['status'] == 'aguardando')
        qtd_em_atendimento = sum(1 for a in fila if a['status'] == 'em_atendimento_humano')

        # Enviando a fila e os contadores para o HTML
        return jsonify({
            "fila": fila,
            "qtd_aguardando": qtd_aguardando,
            "qtd_em_atendimento": qtd_em_atendimento
        })
        
    except Exception as e:
        print("Erro ao buscar fila:", e)
        return jsonify({"fila": [], "qtd_aguardando": 0, "qtd_em_atendimento": 0})
    
@app.post("/admin/assumir")
@admin_required
def admin_assumir():
    dados = request.get_json(force=True) or {}
    atendimento_id = dados.get("atendimento_id")
    if atendimento_id:
        nome_atendente = session['usuario_logado']
        assumir_atendimento(atendimento_id, nome_atendente)
        registrar_evento(atendimento_id, "assumido_por_humano")
    return jsonify({"ok": True})

@app.post("/admin/mensagem")
@admin_required
def admin_mensagem():
    dados = request.get_json(force=True) or {}
    atendimento_id = int(dados.get("atendimento_id", 0))
    telefone = str(dados.get("telefone", "")).strip()
    texto = str(dados.get("texto", "")).strip()

    # Pega o nome do atendente direto da sessão segura
    atendente_nome = session['usuario_logado']

    # Registra no banco de dados o que o atendente digitou com o nome real dele
    registrar_evento(atendimento_id, "msg_atendente", f"{atendente_nome}: {texto}")
    
    # Dispara para o WhatsApp real do cliente
    if telefone:
        send_whatsapp_text(telefone, texto)

    return jsonify({"ok": True})

@app.get("/admin/mensagens/<int:atendimento_id>")
@admin_required
def admin_get_mensagens(atendimento_id):
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT tipo_evento, valor, data_evento 
            FROM atendimento_eventos 
            WHERE atendimento_id = %s 
              AND tipo_evento IN ('msg_usuario', 'msg_atendente', 'resumo_handoff')
            ORDER BY data_evento ASC
        """, (atendimento_id,))
        msgs = cursor.fetchall()
        return jsonify({"mensagens": msgs})
    except Exception as e:
        print("Erro ao buscar mensagens:", e)
        return jsonify({"mensagens": []})
    finally:
        cursor.close()
        conn.close()

@app.post("/admin/encerrar")
@admin_required
def admin_encerrar_rota():
    dados = request.get_json(force=True) or {}
    atendimento_id = dados.get("atendimento_id")
    
    # Pegamos o nome de quem está logado agora
    nome_atendente = session.get('usuario_logado', 'Desconhecido')

    if atendimento_id:
        registrar_evento(atendimento_id, "finalizar", valor=f"Encerrado por {nome_atendente}")
        
        conn = get_conn()
        cursor = conn.cursor()
        sql_update = """
            UPDATE atendimentos 
            SET status = 'finalizado', 
                atendente_chamado = 1,
                atendente_nome = %s, 
                data_fim = NOW() 
            WHERE id = %s
        """
        cursor.execute(sql_update, (nome_atendente, atendimento_id))
        conn.commit() 

        # Código de apagar sessão e enviar WhatsApp continua igual...
        cursor.execute("SELECT telefone FROM sessao_usuario WHERE atendimento_id = %s", (atendimento_id,))
        res = cursor.fetchone()
        if res:
            telefone = res[0] # Se não for dictionary=True, usa índice
            apagar_sessao(telefone)
            send_whatsapp_text(telefone, "✅ Atendimento finalizado.\n\nA equipe do Canal I agradece o seu contato! Sempre que precisar, estamos à disposição!")
            
        cursor.close()
        conn.close()
        
    return jsonify({"ok": True})

@app.route('/admin/historico')
@admin_required
def tela_historico():
    # Só entra quem é da lista USUARIOS_ADMIN
    return render_template('historico.html', usuario=session['usuario_logado'])

@app.get("/admin/api/historico")
@admin_required
def api_historico():
    # Filtros que virão do formulário da nova tela
    data_de = request.args.get('de')
    data_ate = request.args.get('ate')
    busca = request.args.get('busca', '')

    if not data_de or not data_ate:
        return jsonify({"historico": []})

    try:
        conn = get_conn()
        cursor = conn.cursor(dictionary=True)
        
        # Busca no passado sem limite de mês, apenas pelo intervalo escolhido
        sql = """
            SELECT id, telefone, nome, matricula, status, data_inicio, atendente_nome
            FROM atendimentos
            WHERE data_inicio BETWEEN %s AND %s
        """
        params = [f"{data_de} 00:00:00", f"{data_ate} 23:59:59"]

        if busca:
            sql += " AND (nome LIKE %s OR telefone LIKE %s OR matricula LIKE %s)"
            params.extend([f"%{busca}%", f"%{busca}%", f"%{busca}%"])
        
        sql += " ORDER BY data_inicio DESC LIMIT 500"
        
        cursor.execute(sql, params)
        resultados = cursor.fetchall()
        
        for r in resultados:
            if r['data_inicio']:
                r['data_inicio'] = r['data_inicio'].strftime('%d/%m/%Y %H:%M')

        cursor.close()
        conn.close()
        return jsonify({"historico": resultados})
    except Exception as e:
        print("Erro ao processar histórico:", e)
        return jsonify({"historico": []})

# ============================================================
# SIMULADO
# ============================================================
@app.post("/simulated/incoming")
def simulated_incoming():
    agora = datetime.now()
    payload = request.get_json(force=True) or {}

    telefone = str(payload.get("from") or payload.get("telefone") or "").strip()
    mensagem = str(payload.get("text") or payload.get("mensagem") or "").strip()
    message_id = str(payload.get("message_id") or payload.get("external_message_id") or "").strip()

    if not telefone:
        return jsonify({"resposta": "❌ Erro: telefone não informado."}), 400
    if not mensagem:
        return jsonify({"resposta": "❌ Erro: mensagem não informada."}), 400

    txt = handle_incoming(telefone, mensagem, agora, message_id=message_id)
    return jsonify({"resposta": txt}), 200

@app.get("/health")
def health():
    return {"status": "ok"}

# ============================================================
# PAINEL DE DISPAROS
# ============================================================

@app.route('/disparos')
@disparo_required
def painel_disparos():
    return render_template('disparos.html', usuario=session['usuario_logado'])

@app.get('/disparos/api/listar')
@disparo_required
def api_listar_disparos():
    try:
        resultado = listar_disparos()
        return jsonify({"disparos": resultado})
    except Exception as e:
        print("Erro ao listar disparos:", e)
        return jsonify({"disparos": []})

@app.get('/disparos/api/detalhar/<int:disparo_id>')
@disparo_required
def api_detalhar_disparo(disparo_id):
    try:
        resultado = detalhar_disparo(disparo_id)
        return jsonify(resultado)
    except Exception as e:
        print("Erro ao detalhar disparo:", e)
        return jsonify({})

@app.post('/disparos/api/criar')
@disparo_required
def api_criar_disparo():
    try:
        dados = request.get_json(force=True) or {}
        nome_campanha = dados.get('nome_campanha')
        template_nome = dados.get('template_nome')
        numero_id = dados.get('numero_id')
        contatos = dados.get('contatos', [])

        disparo_id = criar_disparo(nome_campanha, template_nome, numero_id, contatos)
        return jsonify({"ok": True, "disparo_id": disparo_id})
    except Exception as e:
        print("Erro ao criar disparo:", e)
        return jsonify({"ok": False, "erro": str(e)})

@app.post('/disparos/api/iniciar/<int:disparo_id>')
@disparo_required
def api_iniciar_disparo(disparo_id):
    try:
        dados = request.get_json(force=True) or {}
        template_nome = dados.get('template_nome')
        numero_id = dados.get('numero_id')
        iniciar_disparo(disparo_id, template_nome, numero_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})

@app.post('/disparos/api/pausar/<int:disparo_id>')
@disparo_required
def api_pausar_disparo(disparo_id):
    try:
        pausar_disparo(disparo_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})

@app.post('/disparos/api/retomar/<int:disparo_id>')
@disparo_required
def api_retomar_disparo(disparo_id):
    try:
        dados = request.get_json(force=True) or {}
        template_nome = dados.get('template_nome')
        numero_id = dados.get('numero_id')
        retomar_disparo(disparo_id, template_nome, numero_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})

@app.post('/disparos/api/reenviar/<int:disparo_id>')
@disparo_required
def api_reenviar_erros(disparo_id):
    try:
        dados = request.get_json(force=True) or {}
        template_nome = dados.get('template_nome')
        numero_id = dados.get('numero_id')
        iniciar_reenvio_erros(disparo_id, template_nome, numero_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})

@app.get('/disparos/api/respostas')
@disparo_required
def api_respostas():
    try:
        disparo_id = request.args.get('disparo_id', type=int)
        resultado = listar_respostas(disparo_id)
        return jsonify({"respostas": resultado})
    except Exception as e:
        return jsonify({"respostas": []})

if __name__ == "__main__":
    socketio.run(app, debug=False, port=5000)
