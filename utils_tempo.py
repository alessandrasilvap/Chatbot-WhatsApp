from datetime import datetime, time
import holidays

# ============================================================
# CONFIG
# ============================================================
# Horário Comercial
DIAS_ATUAIS = {0, 1, 2, 3, 4}  # 0=segunda ... 4=sexta
HORA_INICIO = time(8, 0)
HORA_FIM = time(17, 0)

# Feriados RJ
feriados_rj = holidays.BR(state='RJ')

# Recessos (ponto facultativo)
recessos_comlurb = ["2026-04-02", "2026-04-24"]


def em_horario_comercial(agora: datetime) -> bool:
    hoje_texto = agora.strftime("%Y-%m-%d")

    # Recesso
    if hoje_texto in recessos_comlurb:
        return False

    # Final de semana
    if agora.weekday() not in DIAS_ATUAIS:
        return False

    # Feriado
    if agora.date() in feriados_rj:
        return False

    return HORA_INICIO <= agora.time() <= HORA_FIM


def get_tipo_periodo(agora: datetime) -> str:
    hoje_texto = agora.strftime("%Y-%m-%d")

    # 🔴 Feriado / ponto facultativo
    if hoje_texto in recessos_comlurb or agora.date() in feriados_rj:
        return "feriado"

    # 🔵 Final de semana
    if agora.weekday() not in DIAS_ATUAIS:
        return "fim_de_semana"

    # 🟡 Fora do horário
    if not (HORA_INICIO <= agora.time() <= HORA_FIM):
        return "fora_horario"

    # 🟢 Horário comercial
    return "horario_comercial"
