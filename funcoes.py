import json, time
from datetime import datetime, timedelta
import config
import data

# FUNÇÕES AUXILIARES
def mesclar_scans_jsonl(lines, registros, funcionarios):
    """
    lines: lista de strings JSON no formato:
      {"uid":"AABBCCDD","ts":"YYYY-MM-DDTHH:MM:SS","src":"eeprom"}
    Vamos:
      - ignorar UIDs que NÃO estão cadastrados em `funcionarios`
      - agrupar por (uid, data) e ordenar por hora
      - preencher eventos na ordem: entrada, saida_intervalo, volta_intervalo, saida
    Retorna (novos:int, ignorados:int)
    """
    novos = 0
    ignorados = 0

    uids_validos = set([u.strip().upper() for u in funcionarios.keys()])

    buckets = {}
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue

        uid = (obj.get("uid") or "").strip().upper()
        ts  = (obj.get("ts")  or "").strip()

        if not uid or uid not in uids_validos:
            ignorados += 1
            continue

        if len(ts) < 19:
            ignorados += 1
            continue
        try:
            dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            ignorados += 1
            continue

        data_iso = dt.strftime("%Y-%m-%d")
        hora     = dt.strftime("%H:%M")
        buckets.setdefault((uid, data_iso), []).append(hora)

    for (uid, data_iso), horas in buckets.items():
        horas.sort()
        if uid not in registros:
            registros[uid] = {}
        dia = registros[uid].setdefault(data_iso, {})
        for h in horas:
            if all(ev in dia for ev in config.EVENTOS):
                break
            ev = next((e for e in config.EVENTOS if e not in dia), None)
            if ev and h:
                dia[ev] = h
                novos += 1

    return novos, ignorados

def agora():
    dt = datetime.now()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")

def proximo_evento(dia_dict):
    for ev in config.EVENTOS:
        if ev not in dia_dict:
            return ev
    return None

def extrair_uid(linha: str):
    """Retorna UID válido (HEX, tamanho par entre 8 e 20) ou None."""
    if not linha:
        return None
    s = linha.strip().upper()
    if s.startswith("#") or s in {"READY", "OK", "ERR"}:
        return None
    if s.startswith("UID:"):
        s = s.split(":", 1)[1].strip()
    if config.HEX_RE.match(s) and (8 <= len(s) <= 20) and (len(s) % 2 == 0):
        return s
    return None

def registrar_batida(uid):
    """Registra batida e retorna (ok: bool, msg: str, evento_ou_ERR: str)."""
    uid = uid.strip().upper()
    if not uid:
        return False, "UID vazio", "ERR"

    t = time.time()
    if uid in config.ultimas_batidas and (t - config.ultimas_batidas[uid]) < config.MIN_GAP_SECONDS:
        return False, f"Toque repetido em < {config.MIN_GAP_SECONDS}s", "ERR"
    config.ultimas_batidas[uid] = t

    if uid not in config.funcionarios:
        return False, "UID não cadastrado", "ERR"

    data_str, hora_str = agora()
    if uid not in config.registros:
        config.registros[uid] = {}
    if data_str not in config.registros[uid]:
        config.registros[uid][data_str] = {}

    dia = config.registros[uid][data_str]
    ev = proximo_evento(dia)
    if ev is None:
        return False, "Dia já completo", "ERR"

    dia[ev] = hora_str
    data.salvar_json(config.ARQ_REG, config.registros)
    return True, f"{config.funcionarios[uid]}: {ev.replace('_',' ')} às {hora_str} ({data_str})", ev
