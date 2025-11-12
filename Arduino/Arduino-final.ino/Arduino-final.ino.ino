#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <RTClib.h>
#include <EEPROM.h>

// ===== RC522 =====
#define SS_PIN     10
#define RST_PIN    9
MFRC522 mfrc522(SS_PIN, RST_PIN);

// ===== RTC =====
RTC_DS3231 rtc;

// ===== LEDs =====
#define LED_AMARELO 3
#define LED_VERDE   4
#define LED_VERMELHO 5

// ===== Tempos (RENOMEADOS E PADRONIZADOS) =====
const unsigned long DEBOUNCE_MS      = 1500;  // debounce “rápido” de leitura local
const unsigned long ACK_TIMEOUT_MS   = 1500;  // espera do ACK do PC

// Tempos de feedback visual
const unsigned long LED_SUCESSO_MS   = 1000;  // Tempo do LED Verde/Sucesso
const unsigned long LED_ERRO_MS      = 1000;  // Tempo do LED Vermelho/Erro

const unsigned long OFFLINE_MIN_GAP_SEC = 60;  // anti-dupe offline por UID

// Debounce leitura
String ultimoUID = "";
unsigned long ultimoMillis = 0;

// ----------------------------------------------------------------------
//          EEPROM: BUFFER CIRCULAR DE EMERGÊNCIA
// ----------------------------------------------------------------------
static const int HDR_ADDR    = 0;
static const int HDR_SIZE    = 16;
static const uint32_t MAGIC = 0x504F4E54UL; // 'P''O''N''T'
static const int SLOT_SIZE   = 16;
static const int MAX_SLOTS   = (EEPROM.length() - HDR_SIZE) / SLOT_SIZE;

uint16_t e_head  = 0; // próximo slot p/ escrever
uint16_t e_count = 0; // registros válidos

// ===== helpers EEPROM =====
uint8_t ee_r8(int a){ return EEPROM.read(a); }
void    ee_w8(int a, uint8_t v){ EEPROM.update(a, v); }

uint16_t ee_r16(int a){
  uint16_t v = EEPROM.read(a);
  v |= (uint16_t)EEPROM.read(a+1) << 8;
  return v;
}
void ee_w16(int a, uint16_t v){
  EEPROM.update(a,     (uint8_t)(v & 0xFF));
  EEPROM.update(a + 1, (uint8_t)(v >> 8));
}

uint32_t ee_r32(int a){
  uint32_t v = 0;
  v |= (uint32_t)EEPROM.read(a);
  v |= (uint32_t)EEPROM.read(a+1) << 8;
  v |= (uint32_t)EEPROM.read(a+2) << 16;
  v |= (uint32_t)EEPROM.read(a+3) << 24;
  return v;
}
void ee_w32(int a, uint32_t v){
  EEPROM.update(a,     (uint8_t)(v & 0xFF));
  EEPROM.update(a + 1, (uint8_t)((v >> 8) & 0xFF));
  EEPROM.update(a + 2, (uint8_t)((v >> 16) & 0xFF));
  EEPROM.update(a + 3, (uint8_t)((v >> 24) & 0xFF));
}

int slot_addr(uint16_t idx){
  return HDR_SIZE + (idx % MAX_SLOTS) * SLOT_SIZE;
}

void eeprom_load_header(){
  uint32_t magic = ee_r32(HDR_ADDR);
  if (magic != MAGIC){
    ee_w32(HDR_ADDR, MAGIC);
    ee_w16(HDR_ADDR + 4, 0);
    ee_w16(HDR_ADDR + 6, 0);
    e_head = 0; e_count = 0;
  } else {
    e_head  = ee_r16(HDR_ADDR + 4);
    e_count = ee_r16(HDR_ADDR + 6);
    if (e_head >= MAX_SLOTS)  e_head = 0;
    if (e_count >  MAX_SLOTS) e_count = MAX_SLOTS;
  }
}
void eeprom_save_header(){
  ee_w16(HDR_ADDR + 4, e_head);
  ee_w16(HDR_ADDR + 6, e_count);
}
void eeprom_clear_all(){
  e_head = 0; e_count = 0; eeprom_save_header();
}

void eeprom_push(uint32_t epoch, const byte* uid, byte uid_len){
  if (uid_len > 10) uid_len = 10;
  int a = slot_addr(e_head);
  uint8_t crc = 0;

  ee_w32(a, epoch);
  for(byte i=0;i<4;i++) crc ^= ee_r8(a+i);

  ee_w8(a+4, uid_len);
  crc ^= ee_r8(a+4);

  for(byte i=0;i<10;i++){
    uint8_t b = (i < uid_len) ? uid[i] : 0;
    ee_w8(a+5+i, b);
    crc ^= ee_r8(a+5+i);
  }

  ee_w8(a+15, crc);

  e_head = (e_head + 1) % MAX_SLOTS;
  if (e_count < MAX_SLOTS) e_count++;
  eeprom_save_header();
}

bool eeprom_read_slot(uint16_t idx, uint32_t &epoch, byte *uid, byte &uid_len){
  int a = slot_addr(idx);
  uint8_t crc = 0;

  epoch = ee_r32(a);
  for(byte i=0;i<4;i++) crc ^= ee_r8(a+i);

  uid_len = ee_r8(a+4);
  crc ^= ee_r8(a+4);
  if (uid_len > 10) uid_len = 10;

  for(byte i=0;i<10;i++){
    uid[i] = ee_r8(a+5+i);
    crc ^= ee_r8(a+5+i);
  }

  uint8_t stored = ee_r8(a+15);
  return (crc == stored);
}

// ===== utils e comandos seriais =====
static const char *HX = "0123456789ABCDEF";

String bytes_to_hex(const byte *uid, byte len){
  String s; s.reserve(len*2);
  for(byte i=0;i<len;i++){
    s += HX[uid[i] >> 4];
    s += HX[uid[i] & 0x0F];
  }
  return s;
}

void print_one_json(uint32_t epoch, const byte *uid, byte len){
  DateTime dt = DateTime(epoch);
  char ts[25];
  snprintf(ts, sizeof(ts), "%04d-%02d-%02dT%02d:%02d:%02d",
           dt.year(), dt.month(), dt.day(), dt.hour(), dt.minute(), dt.second());
  String uhex = bytes_to_hex(uid, len);
  Serial.print("{\"uid\":\""); Serial.print(uhex);
  Serial.print("\",\"ts\":\""); Serial.print(ts);
  Serial.println("\",\"src\":\"eeprom\"}");
}

// -------- comandos seriais --------
void cmd_STATUS(){
  Serial.print("MAX_SLOTS="); Serial.print(MAX_SLOTS);
  Serial.print(" HEAD="); Serial.print(e_head);
  Serial.print(" COUNT="); Serial.println(e_count);
}

void cmd_EDUMP(){
  Serial.println("EBEGIN");
  if (e_count == 0){ Serial.println("EEND"); return; }
  uint16_t start = (e_head + MAX_SLOTS - e_count) % MAX_SLOTS;
  for (uint16_t i=0;i<e_count;i++){
    uint16_t idx = (start + i) % MAX_SLOTS;
    uint32_t epoch; byte uid[10]; byte len;
    if (!eeprom_read_slot(idx, epoch, uid, len)) continue;
    print_one_json(epoch, uid, len);
  }
  Serial.println("EEND");
}

void cmd_EDUMP_UID(const String &uid_hex){
  String s = uid_hex; s.trim(); s.toUpperCase();
  if (s.length()==0 || (s.length()%2)!=0 || s.length()>20){ Serial.println("ERR Invalid UID"); return; }
  for (unsigned i=0;i<s.length();i++){
    char c=s[i]; if(!((c>='0'&&c<='9')||(c>='A'&&c<='F'))){ Serial.println("ERR Invalid UID"); return; }
  }
  byte ref[10]; byte rlen = s.length()/2;
  for (int i=0;i<rlen;i++){
    uint8_t hi = (s[2*i]    <= '9') ? s[2*i]-'0' : s[2*i]-'A'+10;
    uint8_t lo = (s[2*i+1] <= '9') ? s[2*i+1]-'0' : s[2*i+1]-'A'+10;
    ref[i] = (hi<<4) | lo;
  }

  Serial.println("EBEGIN");
  if (e_count != 0){
    uint16_t start = (e_head + MAX_SLOTS - e_count) % MAX_SLOTS;
    for (uint16_t i=0;i<e_count;i++){
      uint16_t idx = (start + i) % MAX_SLOTS;
      uint32_t epoch; byte uid[10]; byte len;
      if (!eeprom_read_slot(idx, epoch, uid, len)) continue;
      if (len != rlen) continue;
      bool eq = true; for(byte k=0;k<len;k++) if (uid[k]!=ref[k]) { eq=false; break; }
      if (eq) print_one_json(epoch, uid, len);
    }
  }
  Serial.println("EEND");
}

void cmd_EDUMP_CSV(){
  Serial.println("uid,ts,src");
  if (e_count == 0) return;
  uint16_t start = (e_head + MAX_SLOTS - e_count) % MAX_SLOTS;
  for (uint16_t i=0;i<e_count;i++){
    uint16_t idx = (start + i) % MAX_SLOTS;
    uint32_t epoch; byte uid[10]; byte len;
    if (!eeprom_read_slot(idx, epoch, uid, len)) continue;
    DateTime dt = DateTime(epoch);
    char ts[25];
    snprintf(ts, sizeof(ts), "%04d-%02d-%02dT%02d:%02d:%02d",
              dt.year(), dt.month(), dt.day(), dt.hour(), dt.minute(), dt.second());
    String uhex = bytes_to_hex(uid, len);
    Serial.print(uhex); Serial.print(",");
    Serial.print(ts);  Serial.println(",eeprom");
  }
}

void cmd_ECLEAR(){
  eeprom_clear_all();
  Serial.println("ECLEARED");
}

void cmd_SETTIME(const String &iso){
  String s = iso; s.trim();
  if (s.length() < 19){ Serial.println("ERR Bad ISO time"); return; }
  int y = s.substring(0,4).toInt();
  int m = s.substring(5,7).toInt();
  int d = s.substring(8,10).toInt();
  int H = s.substring(11,13).toInt();
  int M = s.substring(14,16).toInt();
  int S = s.substring(17,19).toInt();
  if (!y||!m||!d){ Serial.println("ERR Bad ISO time"); return; }
  rtc.adjust(DateTime(y,m,d,H,M,S));
  Serial.println("TIMESET");
}

// ----------------------------------------------------------------------
//                        LEDS
// ----------------------------------------------------------------------
void setAllOff(){ 
    digitalWrite(LED_AMARELO, LOW); 
    digitalWrite(LED_VERDE, LOW); 
    digitalWrite(LED_VERMELHO, LOW); 
}
void showYellow(){ 
    digitalWrite(LED_AMARELO, HIGH); 
    digitalWrite(LED_VERDE, LOW); 
    digitalWrite(LED_VERMELHO, LOW); 
}

void showGreen(){ 
    digitalWrite(LED_AMARELO, LOW); 
    digitalWrite(LED_VERDE, HIGH); 
    digitalWrite(LED_VERMELHO, LOW); 
    delay(LED_SUCESSO_MS);
    setAllOff(); 
}

void showRed(){ 
    digitalWrite(LED_AMARELO, LOW); 
    digitalWrite(LED_VERDE, LOW); 
    digitalWrite(LED_VERMELHO, HIGH); 
    delay(LED_ERRO_MS);
    setAllOff(); 
}

// ----------------------------------------------------------------------
//         Comando pendente durante espera de ACK
// ----------------------------------------------------------------------
enum PendingCmd { CMD_NONE, CMD_EDUMP, CMD_ECLEAR, CMD_STATUS, CMD_EDUMP_CSV, CMD_EDUMP_UID, CMD_SETTIME };
volatile PendingCmd pending_cmd = CMD_NONE;
String pending_arg;

int waitAckFromPython(){
  unsigned long start = millis();
  String line = "";
  while (millis() - start < ACK_TIMEOUT_MS){
    while (Serial.available() > 0){
      char c = (char)Serial.read();
      if (c == '\r') continue;
      if (c == '\n'){
        line.trim();
        if (line == "OK")  return 1;
        if (line == "ERR") return 0;

        if (line == "EDUMP"){ pending_cmd = CMD_EDUMP; return 1; }
        if (line == "ECLEAR"){ pending_cmd = CMD_ECLEAR; return 1; }
        if (line == "STATUS"){ pending_cmd = CMD_STATUS; return 1; }
        if (line == "EDUMP_CSV"){ pending_cmd = CMD_EDUMP_CSV; return 1; }
        if (line.startsWith("EDUMP_UID ")){ pending_cmd = CMD_EDUMP_UID; pending_arg = line.substring(10); pending_arg.trim(); return 1; }
        if (line.startsWith("SETTIME ")){ pending_cmd = CMD_SETTIME; pending_arg = line.substring(8); pending_arg.trim(); return 1; }

        line = "";
      } else {
        line += c;
      }
    }
  }
  return -1; // timeout
}

// ----------------------------------------------------------------------
//       Anti-dupe OFFLINE: cache dos últimos 8 UIDs
// ----------------------------------------------------------------------
struct LastSeen {
  byte uid[10];
  byte len;
  uint32_t lastEpoch;
  bool used;
};
LastSeen offline_cache[8]; // ~120 bytes de RAM

bool same_uid(const byte *a, byte alen, const byte *b, byte blen){
  if (alen != blen) return false;
  for (byte i=0;i<alen;i++) if (a[i]!=b[i]) return false;
  return true;
}

int find_in_cache(const byte *uid, byte len){
  for (int i=0;i<8;i++){
    if (offline_cache[i].used && same_uid(offline_cache[i].uid, offline_cache[i].len, uid, len))
      return i;
  }
  return -1;
}

int upsert_cache(const byte *uid, byte len, uint32_t epoch){
  int idx = find_in_cache(uid, len);
  if (idx >= 0){
    offline_cache[idx].lastEpoch = epoch;
    return idx;
  }
  // procura vaga
  for (int i=0;i<8;i++){
    if (!offline_cache[i].used){
      offline_cache[i].used = true;
      offline_cache[i].len = len > 10 ? 10 : len;
      for (byte k=0;k<offline_cache[i].len;k++) offline_cache[i].uid[k] = uid[k];
      offline_cache[i].lastEpoch = epoch;
      return i;
    }
  }
  // sem vaga: sobrescreve a 0 (bem simples)
  offline_cache[0].used = true;
  offline_cache[0].len = len > 10 ? 10 : len;
  for (byte k=0;k<offline_cache[0].len;k++) offline_cache[0].uid[k] = uid[k];
  offline_cache[0].lastEpoch = epoch;
  return 0;
}

// ----------------------------------------------------------------------
//                               SETUP
// ----------------------------------------------------------------------
void setup(){
    pinMode(LED_AMARELO, OUTPUT); 
    pinMode(LED_VERDE, OUTPUT);
    pinMode(LED_VERMELHO, OUTPUT);

    Serial.begin(9600);
    while(!Serial){;}

    Wire.begin();
    rtc.begin();
    // rtc.adjust(DateTime(F(__DATE__), F(__TIME__))); // use 1x se precisar acertar

    SPI.begin();
    mfrc522.PCD_Init();
    delay(50);

    eeprom_load_header();

    // zera cache offline
    for (int i=0;i<8;i++) offline_cache[i].used = false;
}

// ----------------------------------------------------------------------
//                                LOOP
// ----------------------------------------------------------------------
void loop(){
  // ---- comandos imediatos vindos do PC ----
  if (Serial.available()){
    String line = Serial.readStringUntil('\n'); line.trim();
    if (line.length()){
      if (line == "STATUS"){ cmd_STATUS(); return; }
      if (line == "EDUMP"){ cmd_EDUMP(); return; }
      if (line.startsWith("EDUMP_UID ")){ cmd_EDUMP_UID(line.substring(10)); return; }
      if (line == "EDUMP_CSV"){ cmd_EDUMP_CSV(); return; }
      if (line == "ECLEAR"){ cmd_ECLEAR(); return; }
      if (line.startsWith("SETTIME ")){ cmd_SETTIME(line.substring(8)); return; }
    }
  }

  // ---- comandos pendentes (recebidos durante waitAck) ----
  if (pending_cmd != CMD_NONE){
    PendingCmd cmd = pending_cmd; pending_cmd = CMD_NONE;
    switch (cmd){
      case CMD_STATUS:    cmd_STATUS(); break;
      case CMD_EDUMP:     cmd_EDUMP(); break;
      case CMD_EDUMP_UID: cmd_EDUMP_UID(pending_arg); pending_arg = ""; break;
      case CMD_EDUMP_CSV: cmd_EDUMP_CSV(); break;
      case CMD_ECLEAR:    cmd_ECLEAR(); break;
      case CMD_SETTIME:   cmd_SETTIME(pending_arg); pending_arg = ""; break;
      default: break;
    }
    return;
  }

  // ---- leitura RFID ----
  if (!mfrc522.PICC_IsNewCardPresent()) return;
  if (!mfrc522.PICC_ReadCardSerial())    return;

  // status “lendo”
  showYellow();

  // UID em HEX maiúsculo (string só para debug/consistência com Python)
  String uidHex = "";
  for (byte i=0;i<mfrc522.uid.size;i++){
    if (mfrc522.uid.uidByte[i] < 0x10) uidHex += "0";
    uidHex += String(mfrc522.uid.uidByte[i], HEX);
  }
  uidHex.toUpperCase();

  // Debounce de leitura local rápido
  unsigned long agoraMS = millis();
  if (uidHex == ultimoUID && (agoraMS - ultimoMillis) < DEBOUNCE_MS){
    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
    setAllOff();
    return;
  }
  ultimoUID = uidHex;
  ultimoMillis = agoraMS;

  // 1) Envia UID ao Python
  Serial.println(uidHex);

  // 2) Espera ACK: OK (1) / ERR (0) / TIMEOUT (-1)
  int ack = waitAckFromPython();

  setAllOff();

  if (ack == 1) {
    // ONLINE e OK → verde; não grava EEPROM
    showGreen();
  }
  else if (ack == 0) {
    // ONLINE e ERR → vermelho; não grava EEPROM
    showRed();
  }
  else {
    // TIMEOUT: PC OFFLINE → aplica anti-dupe offline e, se passar, grava EEPROM
    uint32_t nowEpoch = rtc.now().unixtime();
    int idx = find_in_cache(mfrc522.uid.uidByte, mfrc522.uid.size);
    
    // 1. Verifica anti-dupe (bateu antes de OFFLINE_MIN_GAP_SEC?)
    if (idx >= 0) {
      uint32_t delta = nowEpoch - offline_cache[idx].lastEpoch;
      
      if (delta < OFFLINE_MIN_GAP_SEC) {
        // IGNORADO por anti-dupe offline: MOSTRA VERMELHO
        showRed(); 
        
        // finaliza cartão e sai
        mfrc522.PICC_HaltA();
        mfrc522.PCD_StopCrypto1();
        return;
      }
      
      // passou: atualiza cache (para que a próxima batida não seja ignorada)
      offline_cache[idx].lastEpoch = nowEpoch;
    } else {
      // primeira vez desse UID no cache: cadastra
      upsert_cache(mfrc522.uid.uidByte, mfrc522.uid.size, nowEpoch);
    }

    // 2. Grava e sinaliza sucesso (Offline OK)
    eeprom_push(nowEpoch, mfrc522.uid.uidByte, mfrc522.uid.size);
    showGreen(); // Feedback visual rápido de sucesso
  }

  // Finaliza comunicação com este cartão
  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();
}