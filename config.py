import re, threading, queue

# CONFIGURAÇÕES E CONSTANTES
ARQ_FUNC = "funcionarios.json"
ARQ_REG  = "registros.json"

BAUDRATE = 9600
TIMEOUT = 1
EVENTOS = ["entrada", "saida_intervalo", "volta_intervalo", "saida"]
MIN_GAP_SECONDS = 60
HEX_RE = re.compile(r'^[0-9A-F]+$')

# VARIAVEIS GLOBAIS
funcionarios = {}
registros = {}
ultimas_batidas = {}
serial_thread_obj = None
serial_stop_flag = threading.Event()
serial_port = None
serial_pause_flag = threading.Event()
serial_connected = False
serial_queue = queue.Queue()    # ('ok'|'err'|'log'|'uid_captured', payload)
PORTA_ATUAL = None
last_export_path = None

capture_uid_mode = False
capture_lock = threading.Lock()