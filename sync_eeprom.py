import json, time, sys, os
from datetime import datetime
import serial

# ====== AJUSTE AQUI ======
PORT = "COM7"          # sua porta serial
BAUD = 9600
TIMEOUT = 1.0          # s

ARQ_REG = "registros.json"   # {UID: {YYYY-MM-DD: {evento: "HH:MM"}}}
EVENTOS = ["entrada", "saida_intervalo", "volta_intervalo", "saida"]


# ---------- util ----------
def carregar_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def salvar_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def mesclar_scans_jsonl(lines, registros):
    """
    lines: lista de strings JSON no formato:
      {"uid":"AABBCCDD","ts":"YYYY-MM-DDTHH:MM:SS","src":"eeprom"}
    Atualiza 'registros' no formato do seu app e retorna quantidade de batidas novas aplicadas.
    """
    novos = 0
    # bucketiza por (uid, data) e ordena por hora
    buckets = {}  # {(uid,data): [HH:MM,...]}
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
        if not uid or len(ts) < 16:
            continue
        try:
            dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
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
            # se o dia já está completo, ignora
            if all(ev in dia for ev in EVENTOS):
                break
            # acha próximo evento faltante
            ev = next((e for e in EVENTOS if e not in dia), None)
            if ev and h:
                dia[ev] = h
                novos += 1

    return novos


# ---------- EDUMP ----------
def ler_edump(ser, timeout_total=15.0):
    """
    Envia EDUMP e lê linhas entre EBEGIN e EEND.
    Retorna (ok: bool, linhas: list[str], msg: str)
    """
    try:
        ser.reset_input_buffer()
    except Exception:
        pass

    ser.write(b"EDUMP\n")

    linhas = []
    started = False
    t0 = time.time()
    while time.time() - t0 < timeout_total:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
        except Exception as e:
            return False, [], f"Leitura serial falhou: {e}"
        if not line:
            continue
        # debug opcional:
        # print("<<", line)
        if line == "EBEGIN":
            started = True
            continue
        if line == "EEND":
            break
        if started:
            linhas.append(line)

    if not started:
        return False, [], "Arduino não respondeu com EBEGIN (EDUMP)."
    return True, linhas, "OK"


def mandar_eclear(ser):
    try:
        ser.write(b"ECLEAR\n")
    except Exception:
        pass


def main():
    print(f"[INFO] Abrindo {PORT} @ {BAUD} ...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=TIMEOUT)
        time.sleep(2)  # dá tempo de resetar
    except Exception as e:
        print(f"[ERRO] Não abriu serial: {e}")
        sys.exit(1)

    ok, linhas, msg = ler_edump(ser)
    if not ok:
        print(f"[ERRO] {msg}")
        ser.close()
        sys.exit(2)

    print(f"[INFO] Recebidas {len(linhas)} linhas da EEPROM")

    registros = carregar_json(ARQ_REG, {})
    novos = mesclar_scans_jsonl(linhas, registros)

    if novos > 0:
        salvar_json(ARQ_REG, registros)
        print(f"[OK] Mescladas {novos} batidas novas em {ARQ_REG}")
        # limpar EEPROM após sucesso
        mandar_eclear(ser)
        print("[OK] ECLEAR enviado")
    else:
        print("[INFO] Nenhuma batida nova para mesclar.")

    ser.close()
    print("[INFO] Concluído.")

if __name__ == "__main__":
    main()
