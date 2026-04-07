from flask import Flask, request, jsonify, session, redirect, render_template
from menusSubmenus3 import texto_menu_principal, texto_submenu, texto_sub_submenu, obter_script, texto_opcoes_pos_script
from bd3 import (
    criar_atendimento, atualizar_atendimento, marcar_handoff, finalizar, registrar_evento,
    obter_status_atendimento, obter_sessao, salvar_sessao, apagar_sessao, get_conn, validar_login
)
import holidays
from datetime import datetime, timedelta, time
import os
import hmac
import hashlib
import requests
from dotenv import load_dotenv

# Carrega variáveis do .env
load_dotenv()

# ============================================================
# CONFIG
# ============================================================
# Tempo de inatividade
TIMEOUT_MINUTOS = 10

# Horário Comercial (aberto para teste)
DIAS_ATUAIS = {0, 1, 2, 3, 4}  # 0=segunda ... 4=sexta
HORA_INICIO = time(8, 0)
HORA_FIM = time(17, 0)

# Feriados do Rio de Janeiro
feriados_rj = holidays.BR(state='RJ')

# Recessos do Rio de Janeiro "AAAA-MM-DD"
recessos_comlurb = ["2026-04-02", "2026-04-20"]

def em_horario_comercial(agora: datetime) -> bool:
    hoje_texto = agora.strftime("%Y-%m-%d")

    # Verifica se é recesso
    if hoje_texto in recessos_comlurb:
        return False

    # Verifica se é fim de semana
    if agora.weekday() not in DIAS_ATUAIS:
        return False

    # Verifica se a data atual cai em um feriado
    if agora.date() in feriados_rj:
        return False
            
    return HORA_INICIO <= agora.time() <= HORA_FIM

# ============================================================
# APP / ENV
# ============================================================
app = Flask(__name__)

WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "")
WA_APP_SECRET = os.getenv("WA_APP_SECRET", "")  # Pode ficar vazio (modo dev)
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_API_VERSION = os.getenv("WA_API_VERSION", "v24.0")
app.secret_key = ""

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
    Extrai mensagens de texto do webhook e retorna lista:
      [{"from":"...", "id":"...", "text":"...", "telefone_bot": "...", "phone_number_id": "..."}]
    """
    results = []
    for e in payload.get("entry", []) or []:
        for c in (e.get("changes", []) or []):
            value = c.get("value", {}) or {}
            
            # Pegando as informações do número do bot
            metadata = value.get("metadata") or {}
            telefone_bot = str(metadata.get("display_phone_number") or "").strip()
            phone_number_id = str(metadata.get("phone_number_id") or "").strip() # Pegando o ID
            
            for m in (value.get("messages", []) or []):
                if m.get("type") != "text":
                    continue
                wa_from = str(m.get("from") or "").strip()
                msg_id = str(m.get("id") or "").strip()
                text = str(((m.get("text") or {}).get("body") or "")).strip()
                
                if wa_from and text:
                    results.append({
                        "from": wa_from, 
                        "id": msg_id, 
                        "text": text, 
                        "telefone_bot": telefone_bot,
                        "phone_number_id": phone_number_id # Guardando o ID
                    })
    return results

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
    if not em_horario_comercial(agora):
        return (
            "⏰ *Nosso atendimento está offline no momento.*\n\n"
            "Funcionamos de segunda a sexta, das 08:00 às 17:00 (exceto feriados).\n"
            "Por favor, envie sua mensagem novamente dentro desse período para que possamos te ajudar!"
        )

    if not telefone:
        return "❌ Erro: telefone não informado."

    sessao = obter_sessao(telefone)

    # Se não existe sessão, cria atendimento + sessão
    if not sessao:
        atendimento_id = criar_atendimento(telefone, telefone_bot)
        registrar_evento(atendimento_id, "inicio_atendimento")

        # DEDUPE no BD
        if message_id:
            try:
                registrar_evento(atendimento_id, "msg_usuario", mensagem, external_message_id=message_id)
            except Exception as e:
                if "Duplicate entry" in str(e) or "duplicate" in str(e).lower():
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

        return (
            "Olá! 👋 Sou o assistente virtual do Canal I da COMLURB.\n\n"
            "Estou aqui para ajudar a tirar suas dúvidas de forma rápida. Mas não se preocupe: se precisar, você poderá escolher falar com um atendente da equipe do Canal I.\n\n"
            "⚠️ *Aviso:* Para agilizar o atendimento de todos, conversas sem interação por mais de 10 minutos são encerradas automaticamente.\n\n"
            "Para começarmos, por favor, digite o seu *nome*."
        )

    atendimento_id = sessao["atendimento_id"]

    # DEDUPE antes de timeout/sessão
    if message_id:
        try:
            registrar_evento(atendimento_id, "msg_usuario", mensagem, external_message_id=message_id)
        except Exception as e:
            if "Duplicate entry" in str(e) or "duplicate" in str(e).lower():
                return "✅ (dedupe-db) mensagem já processada"
            raise
    else:
        registrar_evento(atendimento_id, "msg_usuario", mensagem)

    # Timeout
    ultimo = sessao.get("ultimo_contato") or agora
    if agora - ultimo > timedelta(minutes=TIMEOUT_MINUTOS):
        registrar_evento(atendimento_id, "timeout_finalizado")
        finalizar(atendimento_id)
        apagar_sessao(telefone)
        return (
            "⏱️ Atendimento encerrado por inatividade.\n"
            "Como não tivemos resposta nos últimos 10 minutos, finalizamos esta sessão para liberar a fila. Se precisar de ajuda novamente, envie uma nova mensagem para iniciar um novo atendimento."
        )

    # Atualiza ultimo_contato
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

    # Travar quando humano assumiu
    status_bd = obter_status_atendimento(atendimento_id)
    if status_bd == "em_atendimento_humano":
        if mensagem == "3":
            registrar_evento(atendimento_id, "finalizar")
            finalizar(atendimento_id)
            apagar_sessao(telefone)
            return "✅ Atendimento finalizado. Obrigada!"
        
        # O robô não retorna NADA. Ele apenas fica em silêncio.
        # A mensagem do usuário já foi registrada em 'atendimento_eventos' lá em cima no DEDUPE.
        return ""

    etapa = sessao["etapa"]

    # Etapa: nome
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
            matricula=sessao.get("matricula"),
            menu_id=sessao.get("menu_id"),
            sub_id=sessao.get("sub_id"),
            atendente_chamado=sessao.get("atendente_chamado", 0),
            resumo_handoff_salvo=sessao.get("resumo_handoff_salvo", 0),
            telefone_bot=telefone_bot
        )

        return f"Obrigada, {nome}! 😊 Agora, informe sua *matrícula* (apenas números)."

    # Etapa: matrícula
    if etapa == "matricula":
        if not mensagem.isdigit():
            return "❌ Matrícula inválida. Informe apenas *números*."

        if len(mensagem) != 6:
            return "❌ Matrícula inválida. Informe sua matrícula de 6 dígitos, por favor."

        matricula = mensagem
        atualizar_atendimento(atendimento_id, matricula=matricula)
        registrar_evento(atendimento_id, "informou_matricula", matricula)

        salvar_sessao(
            telefone=telefone,
            atendimento_id=atendimento_id,
            etapa="menu_principal",
            ultimo_contato=agora,
            nome=sessao.get("nome"),
            matricula=matricula,
            telefone_bot=telefone_bot
        )
        return "Cadastro realizado com sucesso ✅\n\n" + texto_menu_principal()

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
            return "📞 Ok! Um atendente humano foi acionado.\n\n📌 Antes, diga-me em *1 frase* o que precisa."

        # Se for uma resposta normal de texto
        atualizar_atendimento(atendimento_id, resposta_bot=script or "SCRIPT_NAO_ENCONTRADO")

        salvar_sessao(
            telefone=telefone, atendimento_id=atendimento_id,
            etapa="pos_resposta", ultimo_contato=agora,
            nome=sessao.get("nome"), matricula=sessao.get("matricula"),
            menu_id=menu_id, sub_id=sub_id, atendente_chamado=0, resumo_handoff_salvo=0,
            telefone_bot=telefone_bot
        )

        if not script:
            return f"Não encontrei essa informação ainda.\n{texto_opcoes_pos_script()}"

        return f"{script}\n{texto_opcoes_pos_script()}"

    # Etapa: pos_resposta
    if etapa == "pos_resposta":
        if mensagem not in ["1", "2"]:
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
                telefone_bot=telefone_bot
            )
            return texto_menu_principal()

        if mensagem == "2":
            registrar_evento(atendimento_id, "finalizar")
            finalizar(atendimento_id)
            apagar_sessao(telefone)
            return "✅ Atendimento finalizado. Obrigada!"

    # Etapa: handoff
    if etapa == "handoff":
        if mensagem == "3":
            registrar_evento(atendimento_id, "finalizar")
            finalizar(atendimento_id)
            apagar_sessao(telefone)
            return "✅ Atendimento finalizado. Obrigada!"

        if not sessao.get("resumo_handoff_salvo"):
            registrar_evento(atendimento_id, "resumo_handoff", mensagem)
            
            atualizar_atendimento(atendimento_id, status="aguardando")
            
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
            return "Perfeito — já enviei ao atendente. Aguarde um instante 🙏"

        return "📞 Você está aguardando um atendente da equipe do Canal I. Se quiser, digite 3 para finalizar."

    return "Algo inesperado aconteceu 😅"

# ============================================================
# WEBHOOK META
# ============================================================
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

        print("\n>>> PAYLOAD BRUTO DA META:", payload, "\n")
        print(">>> KEYS payload:", list(payload.keys()))

        msgs = extract_text_messages(payload)
        print(">>> Mensagens extraidas:", msgs)

        for m in msgs:
            telefone = m["from"]
            mensagem = m["text"]
            message_id = m["id"]
            telefone_bot = m.get("telefone_bot", "")
            phone_number_id = m.get("phone_number_id", "") # Pega o ID

            # Chama o motor de regras
            txt = handle_incoming(telefone, mensagem, datetime.now(), message_id=message_id, telefone_bot=telefone_bot)

            print(">>> RESPOSTA DO BOT:", txt)

            # Envia a resposta de volta se não for repetida
            if txt and "dedupe" not in txt.lower():
                # Agora passamos o phone_number_id para a função de enviar!
                send_whatsapp_text(telefone, txt, phone_number_id=phone_number_id)

        return "OK", 200
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    erro = None
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        senha = request.form.get('senha')
        
        if validar_login(usuario, senha):
            session['usuario_logado'] = usuario # Dá o "crachá" pro usuário
            return redirect('/admin') # Manda ele pro painel
        else:
            erro = "Usuário ou senha incorretos."
            
    # Retorna a tela de login (tanto no GET quanto se der erro no POST)
    return render_template('login.html', erro=erro)

@app.route('/logout')
def logout():
    session.pop('usuario_logado', None) # Toma o crachá de volta
    return redirect('/login')

# ============================================================
# ADMIN - BLINDADO COM VERIFICAÇÃO DE SESSÃO
# ============================================================
@app.route('/admin')
def painel_admin():
    # Se não tiver o crachá, vai pra rua (tela de login)!
    if 'usuario_logado' not in session:
        return redirect('/login')
    
    # Passa o nome do usuário logado para o painel.html
    return render_template('painel.html', usuario=session['usuario_logado'])

@app.get("/admin/fila")
def admin_fila():
    # Verificação de segurança
    if 'usuario_logado' not in session:
        return jsonify({"erro": "Não autorizado"}), 401

    try:
        conn = get_conn()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute('''
            SELECT id, telefone, nome, matricula, status
            FROM atendimentos
            WHERE status IN ('aguardando', 'em_atendimento_humano', 'encerrado', 'finalizado')
            ORDER BY 
                CASE status 
                    WHEN 'aguardando' THEN 1 
                    WHEN 'em_atendimento_humano' THEN 2 
                    ELSE 3 
                END, 
                id DESC
            LIMIT 50
        ''')
        fila = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({"fila": fila})
    except Exception as e:
        print("Erro ao buscar fila:", e)
        return jsonify({"fila": []})
    
@app.post("/admin/assumir")
def admin_assumir():
    # Verificação de segurança
    if 'usuario_logado' not in session:
        return jsonify({"erro": "Não autorizado"}), 401

    dados = request.get_json(force=True) or {}
    atendimento_id = dados.get("atendimento_id")
    if atendimento_id:
        atualizar_atendimento(atendimento_id, status="em_atendimento_humano")
        registrar_evento(atendimento_id, "assumido_por_humano")
    return jsonify({"ok": True})

@app.post("/admin/mensagem")
def admin_mensagem():
    # Verificação de segurança
    if 'usuario_logado' not in session:
        return jsonify({"erro": "Não autorizado"}), 401

    dados = request.get_json(force=True) or {}
    atendimento_id = int(dados.get("atendimento_id", 0))
    telefone = str(dados.get("telefone", "")).strip()
    texto = str(dados.get("texto", "")).strip()

    # Pega o nome do atendente direto da sessão segura, e não do HTML
    atendente_nome = session['usuario_logado']

    # Registra no banco de dados o que o atendente digitou com o nome real dele
    registrar_evento(atendimento_id, "msg_atendente", f"{atendente_nome}: {texto}")
    
    # Dispara para o WhatsApp real do cliente
    if telefone:
        send_whatsapp_text(telefone, texto)

    return jsonify({"ok": True})

@app.get("/admin/mensagens/<int:atendimento_id>")
def admin_get_mensagens(atendimento_id):
    # Verificação de segurança
    if 'usuario_logado' not in session:
        return jsonify({"erro": "Não autorizado"}), 401

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
def admin_encerrar_rota():
    # Verificação de segurança
    if 'usuario_logado' not in session:
        return jsonify({"erro": "Não autorizado"}), 401

    dados = request.get_json(force=True) or {}
    atendimento_id = dados.get("atendimento_id")
    if atendimento_id:
        registrar_evento(atendimento_id, "finalizar")
        finalizar(atendimento_id)
        
        conn = get_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT telefone FROM sessao_usuario WHERE atendimento_id = %s", (atendimento_id,))
        res = cursor.fetchone()
        if res:
            telefone = res['telefone']
            apagar_sessao(telefone)
            send_whatsapp_text(telefone, "✅ Atendimento encerrado.\n\nPosso ajudar em algo mais? Envie qualquer mensagem para iniciar um novo atendimento.")
            
        cursor.close()
        conn.close()
    return jsonify({"ok": True})

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

if __name__ == "__main__":
    app.run(debug=False, port=5000)
