# 🧭 Sistema de Ponto RFID com Arduino + RTC + EEPROM + Comunicação Serial

Este projeto implementa um **sistema de ponto eletrônico inteligente** usando **Arduino**, **leitor RFID (RC522)**, **RTC DS3231** e **memória EEPROM**.
Ele permite registrar acessos (batidas de ponto) **online ou offline**, com **sincronização automática** via comunicação **Serial** com um sistema em **Python + NiceGUI**.

---

## ⚙️ Funcionalidades principais

✅ **Leitura RFID (RC522)**
Detecta o UID de cartões RFID e o envia ao sistema Python.

✅ **Registro offline na EEPROM**
Quando o computador está desconectado, os registros são salvos localmente com **timestamp do RTC**.

✅ **Sincronização automática**
Assim que a conexão volta, todos os registros offline são enviados em formato JSON e o Arduino é limpo.

✅ **Controle por comandos seriais**
O Arduino aceita comandos vindos do Python para gerenciamento e diagnóstico.

✅ **RTC DS3231 integrado**
Garante marcação de horário precisa para registros offline.

✅ **Feedback visual otimizado com LEDs**
- 🟡 Amarelo → Lendo cartão (pisca rápido durante a tentativa de comunicação).
- 🟢 Verde → Batida registrada com **sucesso** (online ou offline).
- 🔴 Vermelho → **Erro** (comunicação falhou ou batida duplicada/rápida - *anti-dupe*).

---

## 🧩 Hardware necessário

| Componente | Descrição |
|-------------|------------|
| Arduino Uno / Nano / Mega | Microcontrolador principal |
| Módulo RFID RC522 | Leitor de cartões/tag RFID |
| RTC DS3231 | Relógio em tempo real com bateria |
| LEDs (verde, vermelho, amarelo) | Indicação visual de status |
| Resistores 220Ω | Para os LEDs |
| Jumpers e protoboard | Conexões elétricas |

---

## 🔌 Conexões recomendadas (Arduino UNO)

| Módulo | Pino | Arduino |
|--------|-------|----------|
| **RC522** | SDA | D10 |
|  | SCK | D13 |
|  | MOSI | D11 |
|  | MISO | D12 |
|  | RST | D9 |
|  | VCC | 3.3V |
|  | GND | GND |
| **RTC DS3231** | SDA | A4 |
|  | SCL | A5 |
|  | VCC | 5V |
|  | GND | GND |
| **LEDs (Ajustados)** | Amarelo | **D3** |
|  | Verde | **D4** |
|  | Vermelho | **D5** |

---

## 🖥️ Comunicação Serial (Arduino ↔ Python)

O Arduino se comunica com o sistema Python pela porta serial (baud rate 9600).
O Python envia e recebe **comandos de texto** (terminados por `\n`).

### 📡 Comandos disponíveis

| Comando | Função |
|----------|--------|
| `STATUS` | Mostra informações sobre o buffer da EEPROM |
| `EDUMP` | Envia todos os registros armazenados (JSON) |
| `EDUMP_UID <uid>` | Envia apenas registros de um UID específico |
| `EDUMP_CSV` | Envia todos os registros em formato CSV |
| `ECLEAR` | Apaga todos os registros da EEPROM |
| `SETTIME <YYYY-MM-DDTHH:MM:SS>` | Ajusta o relógio RTC |
| *(automático)* | Envia o UID do cartão lido para o PC |

---

## 🕹️ Modo Offline Automático

Se o PC estiver desconectado ou não responder:
- O Arduino entra em **modo offline** automaticamente (detectado após um *timeout* seguro);
- As leituras RFID são armazenadas localmente;
- **UX Aprimorada:** O *feedback* visual (LEDs) é rápido (1 segundo), independentemente do *timeout* de comunicação;
- Quando a conexão retorna, o Python envia `EDUMP` e sincroniza todos os registros.

---

## 🧮 Estrutura de Dados (EEPROM)

Cada registro armazenado ocupa um *slot* com:

- **TIMESTAMP:** tempo UNIX (32 bits)
- **UID:** até 10 bytes
- **CRC:** verificação simples (XOR dos bytes)

O buffer é **circular**, ou seja, sobrescreve os registros mais antigos.

---

## 🧠 Anti-Duplicação

O sistema evita leituras duplicadas:
- **Anti-dupe offline:** Cache local de 8 últimos cartões, ignorando novas batidas do mesmo UID por **60 segundos** (com feedback **Vermelho**).
- **Debounce físico:** de 1.5–2s para o mesmo cartão.

---

## 🧰 Requisitos de software

- **Bibliotecas Arduino**
  - `MFRC522` (RFID)
  - `RTClib` (RTC DS3231)
  - `EEPROM` (nativa)
- **Baud rate:** `9600`
- **Versão mínima Arduino IDE:** `1.8.x`

---

## 🧠 Créditos

Projeto desenvolvido por **Guilherme Carvalho** e **João Victor**,
com integração ao sistema Python/NiceGUI para registro de ponto.

Este trabalho foi realizado como parte de um projeto de extensão da **Faculdade Estácio de Sá**,
no curso de **Ciência da Computação**, com foco em soluções de hardware/software.