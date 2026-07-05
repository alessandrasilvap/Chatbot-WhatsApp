from bd3 import get_conn

# Dicionário para transformar números em emojis
EMOJIS_NUMEROS = {
    "0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣",
    "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣",
    "10": "🔟", "11": "1️⃣1️⃣", "12": "1️⃣2️⃣", "13": "1️⃣3️⃣",
    "14": "1️⃣4️⃣", "15": "1️⃣5️⃣", "16": "1️⃣6️⃣", "17": "1️⃣7️⃣", 
    "18": "1️⃣8️⃣", "19": "1️⃣9️⃣", "20": "2️⃣0️⃣"
}

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
            emoji = EMOJIS_NUMEROS.get(ordem, f"{ordem} -")
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
        linhas.append(f"{EMOJIS_NUMEROS['0']} Voltar ao menu principal")

        for ordem, nome in submenus:
            ordem = str(ordem)
            emoji = EMOJIS_NUMEROS.get(ordem, f"{ordem} -")
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
        linhas.append(f"{EMOJIS_NUMEROS['0']} Voltar ao menu anterior")

        for ordem, nome in opcoes:
            ordem = str(ordem)
            emoji = EMOJIS_NUMEROS.get(ordem, f"{ordem} -")
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
