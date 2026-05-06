import os
import requests
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN = os.getenv("WA_ACCESS_TOKEN")
NUMERO_ID_DISPAROS = os.getenv("WA_PHONE_NUMBER_ID_DISPAROS")

def enviar_template(telefone: str, template_nome: str, variaveis: list, numero_id: str = None) -> dict:
    """
    Envia um template aprovado pela Meta para um número de telefone.
    
    Args:
        telefone: número do destinatário com DDI (ex: 5521999999999)
        template_nome: nome exato do template aprovado (ex: processo_seletivo_etapa)
        variaveis: lista com os valores das variáveis (ex: ["João", "Entrevista", "10/05", "09:00", "Rua X"])
        numero_id: phone_number_id do número remetente
    
    Returns:
        dict com 'sucesso' (bool), 'wamid' (str) e 'erro' (str)
    """
    if numero_id is None:
        numero_id = NUMERO_ID_DISPAROS

    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    componentes = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(v or "")} for v in variaveis
            ]
        }
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": telefone,
        "type": "template",
        "template": {
            "name": template_nome,
            "language": {"code": "pt_BR"},
            "components": componentes
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        data = response.json()

        if response.status_code == 200 and "messages" in data:
            wamid = data["messages"][0]["id"]
            return {"sucesso": True, "wamid": wamid, "erro": None}
        else:
            erro = data.get("error", {}).get("message", "Erro desconhecido")
            return {"sucesso": False, "wamid": None, "erro": erro}

    except requests.exceptions.Timeout:
        return {"sucesso": False, "wamid": None, "erro": "Timeout na requisição"}
    except Exception as e:
        return {"sucesso": False, "wamid": None, "erro": str(e)}
