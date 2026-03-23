from flask import Flask, request, jsonify
from menusSubmenus3 import texto_menu_principal, texto_submenu, obter_script
from bd3 import (
    criar_atendimento, atualizar_atendimento, marcar_handoff, finalizar, registrar_evento,
    obter_status_atendimento, listar_fila_handoff, assumir_atendimento,
    obter_sessao, salvar_sessao, apagar_sessao
)
from datetime import datetime, timedelta, time
import os
import hmac
import hashlib
import requests
from dotenv import load_dotenv

# Carrega variáveis do .env (SEM isso, WA_ACCESS_TOKEN pode ficar vazio!)
load_dotenv()

# ============================================================
# CONFIG
# ============================================================
TIMEOUT_MINUTOS = 5

# Horário Comercial (aberto para teste)
DIAS_ATUAIS = {0, 1, 2, 3, 4}  # 0=segunda ... 4=sexta
HORA_INICIO = time(0, 0)
HORA_FIM = time(18, 0)

def em_horario_comercial(agora: datetime) -> bool:
    if agora.weekday() not in DIAS_ATUAIS:
        return True
    return HORA_INICIO <= agora.time() <= HORA_FIM

# ============================================================
# APP / ENV
# ============================================================
app = Flask(__name__)

WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "")
WA_APP_SECRET = os.getenv("WA_APP_SECRET", "")  # pode ficar vazio (modo dev)
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_API_VERSION = os.getenv("WA_API_VERSION", "v24.0")

def verify_signature(req) -> bool:
    """
    Verifica X-Hub-Signature-256 (sha256=...) com HMAC usando o App Secret.
    Se WA_APP_SECRET estiver vazio, fica em modo dev e aceita.
    """
    if not WA_APP_SECRET:
        return True  # modo dev

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
      [{"from":"...","id":"...","text":"..."}]
    """
    results = []
    for e in payload.get("entry", []) or []:
        for c in (e.get("changes", []) or []):
            value = c.get("value", {}) or {}
            for m in (value.get("messages", []) or []):
                if m.get("type") != "text":
                    continue
                wa_from = str(m.get("from") or "").strip()
                msg_id = str(m.get("id") or "").strip()
                text = str(((m.get("text") or {}).get("body") or "")).strip()
                if wa_from and text:
                    results.append({"from": wa_from, "id": msg_id, "text": text})
    return results

# ============================================================
# WhatsApp SEND (Cloud API)
# ============================================================
def send_whatsapp_text(to_wa_id: str, text: str):
    if not WA_ACCESS_TOKEN or not WA_PHONE_NUMBER_ID:
        print("❌ WA_ACCESS_TOKEN ou WA_PHONE_NUMBER_ID vazio no .env.")
        return

    url = f"https://graph.facebook.com/{WA_API_VERSION}/{WA_PHONE_NUMBER_ID}/messages"
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
        print(">>> SEND status:", r.status_code)
        print(">>> SEND body:", r.text)

        if r.status_code >= 300:
            print("❌ Erro ao enviar WhatsApp:", r.status_code, r.text)
        else:
            print("✅ WhatsApp enviado para", to_wa_id)
    except Exception as e:
        print("❌ Exceção ao enviar WhatsApp:", e)

# ============================================================
# CORE handler (motor do bot)
# Agora retorna TEXTO (string), não jsonify.
# ============================================================
def handle_incoming(telefone: str, mensagem: str, agora: datetime, message_id: str = None) -> str:
    if not em_horario_comercial(agora):
        return (
            "⏰ Nosso atendimento funciona de segunda a sexta, das 09:00 às 18:00.\n"
            "Por favor, envie sua mensagem novamente dentro do horário comercial."
        )

    if not telefone:
        return "❌ Erro: telefone não informado."

    sessao = obter_sessao(telefone)

    # Se não existe sessão, cria atendimento + sessão
    if not sessao:
        atendimento_id = criar_atendimento(telefone)
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
            ultimo_contato=agora
        )

        return "Olá! 👋 Sou o atendente virtual. Por favor, informe seu *nome*."

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
            "Se precisar de ajuda novamente, envie qualquer mensagem para iniciar um novo atendimento."
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
    )

    # Travar quando humano assumiu
    status_bd = obter_status_atendimento(atendimento_id)
    if status_bd == "em_atendimento_humano":
        if mensagem == "3":
            registrar_evento(atendimento_id, "finalizar")
            finalizar(atendimento_id)
            apagar_sessao(telefone)
            return "✅ Atendimento finalizado. Obrigada!"
        return "📞 Você está com atendimento humano. Aguarde, por favor. (Digite 3 para finalizar)"

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
        )

        return f"Obrigada, {nome}! 😊 Agora, informe sua *matrícula* (apenas números)."

    # Etapa: matrícula
    if etapa == "matricula":
        if not mensagem.isdigit():
            return "❌ Matrícula inválida. Informe apenas *números*."

        matricula = mensagem
        atualizar_atendimento(atendimento_id, matricula=matricula)
        registrar_evento(atendimento_id, "informou_matricula", matricula)

        salvar_sessao(
            telefone=telefone,
            atendimento_id=atendimento_id,
            etapa="menu_principal",
            ultimo_contato=agora,
            nome=sessao.get("nome"),
            matricula=matricula
        )
        return "Cadastro realizado com sucesso ✅\n\n" + texto_menu_principal()

    # Etapa: menu principal
    if etapa == "menu_principal":
        if mensagem not in ["1", "2", "3"]:
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
        )
        return texto_submenu(menu_id)

    # Etapa: submenu
    if etapa == "submenu":
        menu_id = sessao.get("menu_id")
        if mensagem not in ["1", "2", "3"]:
            return "❌ Opção inválida.\n\n" + texto_submenu(menu_id)

        sub_id = mensagem
        registrar_evento(atendimento_id, "submenu_escolhido", f"{menu_id}:{sub_id}")

        # Menu 3 -> 3 = voltar
        if menu_id == "3" and sub_id == "3":
            salvar_sessao(
                telefone=telefone,
                atendimento_id=atendimento_id,
                etapa="menu_principal",
                ultimo_contato=agora,
                nome=sessao.get("nome"),
                matricula=sessao.get("matricula"),
                menu_id=None,
                sub_id=None
            )
            registrar_evento(atendimento_id, "voltar_menu")
            return texto_menu_principal()

        # Menu 3 -> 1 = handoff direto
        if menu_id == "3" and sub_id == "1":
            atualizar_atendimento(atendimento_id, sub_id=sub_id, resposta_bot="ACESSO_HANDOFF_DIRETO")
            marcar_handoff(atendimento_id)
            registrar_evento(atendimento_id, "handoff")

            salvar_sessao(
                telefone=telefone,
                atendimento_id=atendimento_id,
                etapa="handoff",
                ultimo_contato=agora,
                nome=sessao.get("nome"),
                matricula=sessao.get("matricula"),
                menu_id=menu_id,
                sub_id=sub_id,
                atendente_chamado=1,
                resumo_handoff_salvo=0
            )
            return (
                "📞 Ok! Um atendente humano foi acionado.\n\n"
                "📌 Antes, me diga em *1 frase* o que você precisa (isso ajuda o atendente)."
            )

        script = obter_script(menu_id, sub_id)
        atualizar_atendimento(atendimento_id, sub_id=sub_id, resposta_bot=script or "SCRIPT_NAO_ENCONTRADO")

        salvar_sessao(
            telefone=telefone,
            atendimento_id=atendimento_id,
            etapa="pos_resposta",
            ultimo_contato=agora,
            nome=sessao.get("nome"),
            matricula=sessao.get("matricula"),
            menu_id=menu_id,
            sub_id=sub_id,
            atendente_chamado=sessao.get("atendente_chamado", 0),
            resumo_handoff_salvo=sessao.get("resumo_handoff_salvo", 0),
        )

        if not script:
            return (
                "Não encontrei esse script ainda. Posso te ajudar em algo mais?\n"
                "1 - Voltar ao menu\n2 - Chamar atendente\n3 - Finalizar"
            )

        return (
            script + "\n\nPosso ajudar em algo mais?\n"
            "1 - Voltar ao menu\n2 - Chamar atendente\n3 - Finalizar"
        )

    # Etapa: pos_resposta
    if etapa == "pos_resposta":
        if mensagem not in ["1", "2", "3"]:
            return "❌ Opção inválida.\n1 - Voltar ao menu\n2 - Chamar atendente\n3 - Finalizar"

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
                sub_id=None
            )
            return texto_menu_principal()

        if mensagem == "2":
            marcar_handoff(atendimento_id)
            registrar_evento(atendimento_id, "handoff")
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
                resumo_handoff_salvo=0
            )
            return (
                "📞 Ok! Um atendente humano foi acionado.\n\n"
                "📌 Antes, me diga em *1 frase* o que você precisa (isso ajuda o atendente)."
            )

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
                resumo_handoff_salvo=1
            )
            return "Perfeito — já enviei ao atendente. Aguarde um instante 🙏"

        return "📞 Você está aguardando um atendente humano. Se quiser, digite 3 para finalizar."

    return "Algo inesperado aconteceu 😅"

# ============================================================
# WEBHOOK META
# ============================================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # 1. A Meta usa GET apenas uma vez para verificar se a URL é sua
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

    # 2. A Meta usa POST toda vez que um usuário mandar mensagem
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

            # Chama o motor de regras
            txt = handle_incoming(telefone, mensagem, datetime.now(), message_id=message_id)

            print(">>> RESPOSTA DO BOT:", txt)

            # Envia a resposta de volta se não for repetida
            if txt and "dedupe" not in txt.lower():
                send_whatsapp_text(telefone, txt)

        return "OK", 200

# ============================================================
# ADMIN
# ============================================================
@app.get("/admin/fila")
def admin_fila():
    fila = listar_fila_handoff()
    return jsonify({"fila": fila})

@app.post("/admin/assumir")
def admin_assumir():
    dados = request.get_json(force=True) or {}
    atendimento_id = int(dados["atendimento_id"])
    atendente_nome = str(dados["atendente_nome"]).strip()

    ok = assumir_atendimento(atendimento_id, atendente_nome)
    if ok:
        registrar_evento(atendimento_id, "atendente_assumiu", atendente_nome)
        return jsonify({"ok": True})

    return jsonify({"ok": False, "erro": "Não foi possível assumir (talvez já não esteja em handoff)."}), 400

@app.post("/admin/mensagem")
def admin_mensagem():
    dados = request.get_json(force=True) or {}
    atendimento_id = int(dados["atendimento_id"])
    atendente_nome = str(dados["atendente_nome"]).strip()
    texto = str(dados["texto"]).strip()

    registrar_evento(atendimento_id, "msg_atendente", f"{atendente_nome}: {texto}")
    return jsonify({"ok": True})

@app.post("/admin/encerrar")
def admin_encerrar():
    dados = request.get_json(force=True) or {}
    atendimento_id = int(dados["atendimento_id"])
    motivo = str(dados.get("motivo", "Resolvido")).strip()

    registrar_evento(atendimento_id, "encerrado_atendente", motivo)
    finalizar(atendimento_id)
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
