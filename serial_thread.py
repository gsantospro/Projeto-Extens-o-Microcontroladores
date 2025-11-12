import time
import serial
import serial.tools.list_ports
import config
import funcoes
import data

# FUNÇÕES DE SINCRONIZAÇÃO (FORA DA THREAD)
def _edump_core(ser, timeout_total=15.0):
    """Executa o EDUMP e retorna (started: bool, linhas: list)."""
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    
    ser.write(b"EDUMP\r\n") 
    
    linhas, started = [], False
    t0 = time.time()
    
    while time.time() - t0 < timeout_total:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if not line:
            continue
        if line == 'EBEGIN':
            started = True
            continue
        if line == 'EEND':
            break
        if started:
            linhas.append(line)
            
    return started, linhas

def _drain_serial(port, dur=0.8):
    """Drena o lixo do buffer serial após o reset do Arduino."""
    end = time.time() + dur
    while time.time() < end:
        try:
            line = port.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                break
        except Exception:
            break

def _do_initial_sync(ar, port_name):
    """Lógica completa de sincronização EDUMP após a conexão."""
    config.serial_queue.put(("log", f"[SYNC] Conectado em {port_name}. Aguardando reset do Arduino (3.0s)..."))
    
    time.sleep(3.0) 
    
    _drain_serial(ar)
    
    try:
        started, linhas = _edump_core(ar, timeout_total=15.0)

        if not started:
            config.serial_queue.put(("log", "[SYNC] 1ª tentativa sem EBEGIN; tentando novamente (1.0s)..."))
            time.sleep(1.0) 
            _drain_serial(ar, dur=0.5)
            started, linhas = _edump_core(ar, timeout_total=15.0)

        if not started:
            config.serial_queue.put(("log", "[SYNC] Arduino não respondeu ao EDUMP na conexão."))
            return

        try:
            novos, ignorados = funcoes.mesclar_scans_jsonl(linhas, config.registros, config.funcionarios)
        except TypeError:
            novos = funcoes.mesclar_scans_jsonl(linhas, config.registros)
            ignorados = 0

        if novos > 0:
            data.salvar_json(config.ARQ_REG, config.registros)
            try:
                ar.write(b"ECLEAR\r\n")
            except Exception:
                pass
            msg = f"[SYNC] Importadas {novos} batidas pendentes"
            if ignorados:
                msg += f" • {ignorados} ignoradas (UID não cadastrado)"
            config.serial_queue.put(("ok", msg))
            config.serial_queue.put(("update_data", "sync_completo")) # Sinal para UI
        else:
            if ignorados:
                config.serial_queue.put(("log", f"[SYNC] 0 válidas, {ignorados} ignoradas (UID não cadastrado)."))
            else:
                config.serial_queue.put(("log", "[SYNC] Sem batidas pendentes na EEPROM."))

    except Exception as e:
        config.serial_queue.put(("err", f"[SYNC] Falha ao processar EDUMP: {e}"))


# FUNÇÃO DA THREAD PRINCIPAL
def serial_worker(port_name, do_initial_sync: bool = True):
    try:
        with serial.Serial(
            port_name, 
            config.BAUDRATE, 
            timeout=config.TIMEOUT,
            dsrdtr=True, 
            rtscts=True
        ) as ar:
            config.serial_port = ar
            config.serial_connected = True
            
            if do_initial_sync:
                _do_initial_sync(ar, port_name)

            while not config.serial_stop_flag.is_set():
                
                if config.serial_pause_flag.is_set():
                    time.sleep(0.05)
                    continue

                try:
                    linha = ar.readline().decode("utf-8", errors="ignore").strip()
                    if not linha:
                        continue
                        
                    uid = funcoes.extrair_uid(linha)
                    if uid is None:
                        continue

                    with config.capture_lock:
                        if config.capture_uid_mode: 
                            try:
                                ar.write(b"OK\r\n")
                            except Exception as ew:
                                config.serial_queue.put(("log", f"[WARN] Falha ACK (captura): {ew}"))
                            config.serial_queue.put(("uid_captured", uid))
                            config.capture_uid_mode = False
                            continue

                    ok, info, evento = funcoes.registrar_batida(uid)
                    try:
                        ar.write(b"OK\r\n" if ok else b"ERR\r\n")
                    except Exception as ew:
                        config.serial_queue.put(("log", f"[WARN] Falha ao enviar ACK: {ew}"))

                    if ok:
                        config.serial_queue.put(("ok", f"[OK] {info}"))
                        config.serial_queue.put(("update_data", "nova_batida"))
                    else:
                        config.serial_queue.put(("err", f"[ERR] UID {uid}: {info}"))

                except Exception as e:
                    config.serial_queue.put(("log", f"[WARN] Leitura: {e}"))
                    time.sleep(0.3)
                    
    except serial.SerialException as e:
        config.serial_queue.put(("err", f"[ERRO GRAVE] Falha ao abrir a porta {port_name}: {e}"))
    except Exception as e:
        config.serial_queue.put(("err", f"[ERRO] Falha geral na thread: {e}"))
    finally:
        config.serial_connected = False
        config.serial_port = None
        config.serial_queue.put(("log", "[SERIAL] Desconectado"))


def listar_portas():
    return [p.device for p in serial.tools.list_ports.comports()]