from bd3 import get_conn

# Dicionário para transformar números em emojis
def numero_para_emoji(numero):
    numero = str(numero)

    # O 10 já possui um emoji próprio
    if numero == "10":
        return "🔟"

    return "".join(f"{n}\uFE0F\u20E3" for n in numero)

def texto_menu_principal():
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT ordem, nome
            FROM canal_menu
            WHERE ativo = 1
            ORDER BY ordem
        """)

        menus = cur.fetchall()

        linhas = ["*Como posso ajudar? Digite apenas o número:* \n"]

        for ordem, nome in menus:
            ordem = str(ordem)
            emoji = numero_para_emoji(ordem)
            linhas.append(f"{emoji} {nome}")

        return "\n".join(linhas)

    finally:
        cur.close()
        conn.close()

  def texto_submenu(menu_id: str):
    conn = get_conn()
    cur = conn.cursor()

    try:
        # Busca o nome do menu
        cur.execute("""
            SELECT nome
            FROM canal_menu
            WHERE ordem = %s
        """, (menu_id,))

        resultado = cur.fetchone()

        if not resultado:
            return "Menu não encontrado."

        nome_menu = resultado[0]

        # Busca os submenus
        cur.execute("""
            SELECT ordem, nome
            FROM canal_submenu
            WHERE menu_id =
            (
                SELECT id
                FROM canal_menu
                WHERE ordem = %s
            )
            AND ativo = 1
            ORDER BY ordem
        """, (menu_id,))

        submenus = cur.fetchall()

        linhas = [f"*{nome_menu}*\nEscolha uma opção:\n"]

        # Opção fixa
        linhas.append(f"{numero_para_emoji(0)} Voltar ao menu principal")

        for ordem, nome in submenus:
            ordem = str(ordem)
            emoji = numero_para_emoji(ordem)
            linhas.append(f"{emoji} {nome}")

        return "\n".join(linhas)

    finally:
        cur.close()
        conn.close()

  def texto_sub_submenu(menu_id: str, sub_id: str):
    conn = get_conn()
    cur = conn.cursor()

    try:
        # Busca o nome do submenu
        cur.execute("""
            SELECT s.nome
            FROM canal_submenu s
            INNER JOIN canal_menu m
                ON s.menu_id = m.id
            WHERE m.ordem = %s
              AND s.ordem = %s
        """, (menu_id, sub_id))

        resultado = cur.fetchone()

        if not resultado:
            return "Submenu não encontrado."

        nome_submenu = resultado[0]

        # Busca as opções
        cur.execute("""
            SELECT o.ordem, o.nome
            FROM canal_opcao o
            INNER JOIN canal_submenu s
                ON o.submenu_id = s.id
            INNER JOIN canal_menu m
                ON s.menu_id = m.id
            WHERE m.ordem = %s
              AND s.ordem = %s
              AND o.ativo = 1
            ORDER BY o.ordem
        """, (menu_id, sub_id))

        opcoes = cur.fetchall()

        linhas = [f"*{nome_submenu}*\nEscolha uma opção:\n"]

        # Opção fixa
        linhas.append(f"{numero_para_emoji(0)} Voltar ao menu anterior")

        for ordem, nome in opcoes:
            ordem = str(ordem)
            emoji = numero_para_emoji(ordem)
            linhas.append(f"{emoji} {nome}")

        return "\n".join(linhas)

    finally:
        cur.close()
        conn.close()

def obter_script(menu_id: str, sub_id: str, opcao_id: str):
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT r.resposta
            FROM canal_resposta r
            INNER JOIN canal_opcao o
                ON r.opcao_id = o.id
            INNER JOIN canal_submenu s
                ON o.submenu_id = s.id
            INNER JOIN canal_menu m
                ON s.menu_id = m.id
            WHERE m.ordem = %s
              AND s.ordem = %s
              AND o.ordem = %s
              AND r.ativo = 1
        """, (menu_id, sub_id, opcao_id))

        resultado = cur.fetchone()

        if resultado:
            return resultado[0]

        return None

    finally:
        cur.close()
        conn.close()

def texto_opcoes_pos_script():
    linhas = [
        "\n*Posso ajudar em algo mais?*",
        f"{numero_para_emoji(0)} Voltar ao menu anterior",
        f"{numero_para_emoji(1)} Voltar ao menu principal",
        f"{numero_para_emoji(2)} Finalizar atendimento",
    ]
    return "\n".join(linhas)

def obter_nome_menu(menu_id: str):
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT nome
            FROM canal_menu
            WHERE ordem = %s
              AND ativo = 1
        """, (menu_id,))

        resultado = cur.fetchone()

        if resultado:
            return resultado[0]

        return None

    finally:
        cur.close()
        conn.close()

def obter_nome_submenu(menu_id: str, submenu_id: str):
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT s.nome
            FROM canal_submenu s
            INNER JOIN canal_menu m
                ON s.menu_id = m.id
            WHERE m.ordem = %s
              AND s.ordem = %s
              AND s.ativo = 1
        """, (menu_id, submenu_id))

        resultado = cur.fetchone()

        if resultado:
            return resultado[0]

        return None

    finally:
        cur.close()
        conn.close()

def obter_nome_opcao(menu_id: str, submenu_id: str, opcao_id: str):
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT o.nome
            FROM canal_opcao o
            INNER JOIN canal_submenu s
                ON o.submenu_id = s.id
            INNER JOIN canal_menu m
                ON s.menu_id = m.id
            WHERE m.ordem = %s
              AND s.ordem = %s
              AND o.ordem = %s
              AND o.ativo = 1
        """, (menu_id, submenu_id, opcao_id))

        resultado = cur.fetchone()

        if resultado:
            return resultado[0]

        return None

    finally:
        cur.close()
        conn.close()
