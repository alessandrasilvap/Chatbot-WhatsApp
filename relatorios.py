import pymysql
from bd3 import get_conn
from menusSubmenus3 import MENU_PRINCIPAL, SUBMENUS, SUBSUBMENUS

"""
Módulo de relatórios do painel administrativo (Canal I).

Reúne as queries usadas pelas 4 sub-abas da tela de Relatórios:
1. Operacional  -> tempo real (sempre HOJE)
2. Performance  -> filtro de data
3. Gestão       -> filtro de data
4. Análise      -> filtro de data (tópicos mais selecionados)

Reaproveita get_conn() do bd3.py e os dicionários de menus do
menusSubmenus3.py (MENU_PRINCIPAL, SUBMENUS, SUBSUBMENUS) para traduzir
os IDs em nomes legíveis no relatório de Análise.

OBS: quando os menus forem migrados para uma tabela no banco, a função
_traduzir_topico() é o único ponto que precisa mudar (troca os dicionários
por um SELECT na tabela nova).
"""

def _traduzir_topico(menu_id, sub_id, sub_sub_id):
    nome_menu = MENU_PRINCIPAL.get(menu_id, f"Menu {menu_id}") if menu_id else None
    nome_sub = (
        SUBMENUS.get(menu_id, {}).get(sub_id, f"Submenu {sub_id}")
        if menu_id and sub_id else None
    )
    nome_subsub = (
        SUBSUBMENUS.get((menu_id, sub_id), {}).get(sub_sub_id, f"Opção {sub_sub_id}")
        if menu_id and sub_id and sub_sub_id else None
    )
    return nome_menu, nome_sub, nome_subsub

# ============================================================
# 1. RELATÓRIO OPERACIONAL (tempo real, sempre HOJE)
# ============================================================
def relatorio_operacional():
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute("""
            SELECT
                SUM(DATE(data_inicio) = CURDATE()) AS total_hoje,
                SUM(DATE(data_inicio) = CURDATE() AND status IN ('handoff','aguardando')) AS aguardando_hoje,
                SUM(DATE(data_inicio) = CURDATE() AND status = 'em_atendimento_humano') AS em_atendimento_hoje,
                SUM(status = 'finalizado' AND DATE(data_fim) = CURDATE()) AS finalizados_hoje
            FROM atendimentos
            WHERE DATE(data_inicio) = CURDATE() OR DATE(data_fim) = CURDATE()
        """)
        contadores = cur.fetchone() or {}

        cur.execute("""
            SELECT AVG(espera_humano_min) AS tempo_espera
            FROM vw_handoff_espera
            WHERE DATE(data_inicio) = CURDATE()
        """)
        espera = cur.fetchone() or {}

        cur.execute("""
            SELECT AVG(duracao_humano_min) AS tempo_atendimento
            FROM vw_atendimentos_base
            WHERE DATE(data_fim) = CURDATE()
        """)
        atendimento = cur.fetchone() or {}

        return {
            "total_hoje": int(contadores.get("total_hoje") or 0),
            "aguardando_hoje": int(contadores.get("aguardando_hoje") or 0),
            "em_atendimento_hoje": int(contadores.get("em_atendimento_hoje") or 0),
            "finalizados_hoje": int(contadores.get("finalizados_hoje") or 0),
            "tempo_medio_espera": (
                round(float(espera["tempo_espera"]), 1)
                if espera.get("tempo_espera") is not None else None
            ),
            "tempo_medio_atendimento": (
                round(float(atendimento["tempo_atendimento"]), 1)
                if atendimento.get("tempo_atendimento") is not None else None
            ),
        }
    finally:
        cur.close()
        conn.close()

# ============================================================
# 2. RELATÓRIO DE PERFORMANCE (filtro de data)
# ============================================================
def relatorio_performance(de, ate):
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(atendente_chamado = 0) AS so_bot,
                SUM(atendente_chamado = 1) AS com_atendente
            FROM atendimentos
            WHERE DATE(data_inicio) BETWEEN %s AND %s
        """, (de, ate))
        contadores = cur.fetchone() or {}

        cur.execute("""
            SELECT AVG(espera_humano_min) AS tempo_espera
            FROM vw_handoff_espera
            WHERE DATE(data_inicio) BETWEEN %s AND %s
        """, (de, ate))
        espera = cur.fetchone() or {}

        cur.execute("""
            SELECT AVG(duracao_humano_min) AS tempo_atendimento
            FROM vw_atendimentos_base
            WHERE DATE(data_inicio) BETWEEN %s AND %s
        """, (de, ate))
        atendimento = cur.fetchone() or {}

        return {
            "total": int(contadores.get("total") or 0),
            "so_bot": int(contadores.get("so_bot") or 0),
            "com_atendente": int(contadores.get("com_atendente") or 0),
            "tempo_medio_espera": (
                round(float(espera["tempo_espera"]), 1)
                if espera.get("tempo_espera") is not None else None
            ),
            "tempo_medio_atendimento": (
                round(float(atendimento["tempo_atendimento"]), 1)
                if atendimento.get("tempo_atendimento") is not None else None
            ),
        }
    finally:
        cur.close()
        conn.close()

# ============================================================
# 3. RELATÓRIO DE GESTÃO (filtro de data)
# ============================================================
def relatorio_gestao(de, ate):
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        # Fora do expediente / fim de semana / feriado / horário comercial
        cur.execute("""
            SELECT tipo_periodo, COUNT(*) AS qtd
            FROM atendimentos
            WHERE DATE(data_inicio) BETWEEN %s AND %s
            GROUP BY tipo_periodo
        """, (de, ate))
        por_periodo = cur.fetchall()

        # Atendimentos por dia da semana (1=domingo ... 7=sábado, padrão MySQL)
        cur.execute("""
            SELECT DAYOFWEEK(data_inicio) AS dia, COUNT(*) AS qtd
            FROM atendimentos
            WHERE DATE(data_inicio) BETWEEN %s AND %s
            GROUP BY dia
            ORDER BY dia
        """, (de, ate))
        por_dia_semana = cur.fetchall()

        # Pico de atendimento por horário (0-23h)
        cur.execute("""
            SELECT HOUR(data_inicio) AS hora, COUNT(*) AS qtd
            FROM atendimentos
            WHERE DATE(data_inicio) BETWEEN %s AND %s
            GROUP BY hora
            ORDER BY hora
        """, (de, ate))
        por_hora = cur.fetchall()

        # Atendimentos por atendente (via atendente_id -> atendentes.usuario)
        cur.execute("""
            SELECT t.usuario AS atendente, COUNT(*) AS qtd
            FROM atendimentos a
            JOIN atendentes t ON a.atendente_id = t.id
            WHERE DATE(a.data_inicio) BETWEEN %s AND %s
            GROUP BY t.usuario
            ORDER BY qtd DESC
        """, (de, ate))
        por_atendente = cur.fetchall()

        return {
            "por_periodo": por_periodo,
            "por_dia_semana": por_dia_semana,
            "por_hora": por_hora,
            "por_atendente": por_atendente,
        }
    finally:
        cur.close()
        conn.close()

# ============================================================
# 4. RELATÓRIO DE ANÁLISE (tópicos mais selecionados)
# ============================================================
def relatorio_analise(de, ate, limite=30):
    conn = get_conn()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute("""
            SELECT menu_id, sub_id, sub_sub_id, COUNT(*) AS qtd
            FROM atendimentos
            WHERE DATE(data_inicio) BETWEEN %s AND %s
              AND menu_id IS NOT NULL
            GROUP BY menu_id, sub_id, sub_sub_id
            ORDER BY qtd DESC
            LIMIT %s
        """, (de, ate, limite))
        linhas = cur.fetchall()

        resultado = []
        for l in linhas:
            nome_menu, nome_sub, nome_subsub = _traduzir_topico(
                l["menu_id"], l["sub_id"], l["sub_sub_id"]
            )
            resultado.append({
                "menu": nome_menu,
                "submenu": nome_sub,
                "sub_submenu": nome_subsub,
                "qtd": l["qtd"],
            })
        return resultado
    finally:
        cur.close()
        conn.close()
