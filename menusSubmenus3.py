# Menus PY
MENU_PRINCIPAL = {
    "1": "Benefícios",
    "2": "Descontos",
    "3": "Outros assuntos"
}

SUBMENUS = {
    "1": { # Benefícios
        "1": "VR - Quanto cai?",
        "2": "VT - Como solicitar?",
        "3": "pLANO DE SAÚDE - dESCONTO",
    },

    "2": { # Descontos
        "1": "Desconto em folha",
        "2": "Convênios e parcerias",
        "3": "Reembolso"
    },

    "3": { # Outros
        "1": "Falar com atendente",
        "2": "Abrir Solicitação",
        "3": "Voltar",
    },
}

SCRIPTS = {
    ("1", "1"): "🟢 VR: O vale-refeição é depositado todo dia 05.",
    ("1", "2"): "🟢 VT: Para solicitar, envie seu endereço completo para o RH.",
    ("1", "3"): "🟢 Plano de saúde: O desconto varia por faixa e dependentes (consulte o RH).",

    ("2", "1"): "💸 Desconto em folha: aparece no holerite no fim do mês.",
    ("2", "2"): "💸 Convênios: temos parcerias com academias e cursos (lista no portal interno).",
    ("2", "3"): "💸 Reembolso: envie nota fiscal e formulário em até 30 dias.",

    ("3", "1"): "📞 Ok! Vou chamar um atendente humano.",
    ("3", "2"): "📝 Vamos abrir uma solicitação (vamos implementar isso na próxima etapa).",
    ("3", "3"): "↩️ Voltando ao menu principal...",
}

def texto_menu_principal():
    linhas = ["Como posso ajudar? Digite o número: "]
    for k, v in MENU_PRINCIPAL.items():
        linhas.append(f"{k} - {v}")
    return "\n".join(linhas)

def texto_submenu(menu_id: str):
    submenu = SUBMENUS.get(menu_id, {})
    linhas = [f"{MENU_PRINCIPAL.get(menu_id, 'Opção')} - Escolha uma opção:"]
    for k, v in submenu.items():
        linhas.append(f"{k} - {v}")
    return "\n".join(linhas)

def obter_script(menu_id: str, sub_id: str):
    return SCRIPTS.get((menu_id, sub_id))
