/*
 * EPP Monitor - firmware del Arduino UNO (control de acceso)
 *
 * El UNO solo "siente y ejecuta": lee los 2 HC-SR04, el sensor de huella R307S y 2
 * pulsadores, mueve el servo SG90 (cerradura) y escribe en el LCD 16x2 I2C.
 * Toda la lógica (intentos, tiempos, quién está dentro) vive en la PC.
 *
 * Comunicación: USB serial a 115200 baudios, una línea JSON por mensaje.
 * Protocolo completo: docs/PROTOCOLO_SERIAL.md
 *
 * Librerías (Administrador de bibliotecas de Arduino IDE):
 *   - "Adafruit Fingerprint Sensor Library"
 *   - "LiquidCrystal I2C" (Frank de Brabander)
 *   - Servo (incluida)
 *
 * IMPORTANTE: por el puerto serie (USB) solo deben salir líneas JSON. No uses
 * Serial.print para depurar mientras el backend está conectado.
 */

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SoftwareSerial.h>
#include <Adafruit_Fingerprint.h>
#include <Servo.h>

// ----------------------------------------------------------------- pines
const uint8_t TRIG1 = 4;   // HC-SR04 #1 (entrada, lado de la fila)
const uint8_t ECHO1 = 5;
const uint8_t TRIG2 = 6;   // HC-SR04 #2 (interior, después de la huella)
const uint8_t ECHO2 = 7;
const uint8_t FP_RX = 2;   // el UNO recibe  <- TX del R307S
const uint8_t FP_TX = 3;   // el UNO envía   -> RX del R307S (con divisor 5V -> 3.3V)
const uint8_t SERVO_PIN = 9;
const uint8_t BTN_ENTRANCE = 10;   // Asistencia Técnica (entrada), a GND con INPUT_PULLUP
const uint8_t BTN_WORKAREA = 11;   // Asistencia Técnica (área de trabajo)
const uint8_t LCD_ADDRESS = 0x27;  // si no enciende prueba 0x3F (escáner I2C)

// ----------------------------------------------------------------- ajustes
const int SERVO_OPEN_ANGLE = 90;
const int SERVO_CLOSED_ANGLE = 0;
const unsigned long SERVO_DETACH_MS = 700;     // libera el servo para evitar vibración
const unsigned long HEARTBEAT_MS = 2000;
const unsigned long PRESENCE_REPEAT_MS = 3000; // repite "presence" mientras siga alguien
const unsigned long BUTTON_LOCKOUT_MS = 1000;
const uint8_t NEAR_READS = 3;                  // lecturas seguidas para confirmar presencia
const uint8_t FAR_READS = 5;                   // lecturas seguidas para confirmar ausencia

// ----------------------------------------------------------------- objetos
LiquidCrystal_I2C lcd(LCD_ADDRESS, 16, 2);
SoftwareSerial fpSerial(FP_RX, FP_TX);
Adafruit_Fingerprint finger(&fpSerial);
Servo doorServo;

bool fpOk = false;
unsigned long lastHeartbeat = 0;
unsigned long lastFpCheck = 0;

// --- sensores de proximidad
struct Presence {
  uint8_t trig;
  uint8_t echo;
  int threshold;        // cm
  uint8_t nearCount;
  uint8_t farCount;
  bool present;
  unsigned long lastEmit;
};
Presence ps[2] = {
  {TRIG1, ECHO1, 80, 0, 0, false, 0},
  {TRIG2, ECHO2, 80, 0, 0, false, 0},
};
uint8_t sensorTurn = 0;
unsigned long nextSensorRead = 0;

// --- autenticación
bool authActive = false;
unsigned long authDeadline = 0;

// --- registro de huella
enum EnrollState { ENR_NONE, ENR_PLACE1, ENR_REMOVE, ENR_PLACE2 };
EnrollState enr = ENR_NONE;
uint8_t enrSlot = 0;
unsigned long enrDeadline = 0;

// --- servo
bool servoAttached = false;
unsigned long servoDetachAt = 0;

// --- botones
unsigned long btnLast[2] = {0, 0};
bool btnWasDown[2] = {false, false};

// --- entrada serial
char lineBuf[112];
uint8_t lineLen = 0;

// ================================================================= utilidades
void lcdShow(const char* l1, const char* l2) {
  char row[17];
  for (uint8_t r = 0; r < 2; r++) {
    const char* text = r == 0 ? l1 : l2;
    memset(row, ' ', 16);
    row[16] = '\0';
    for (uint8_t i = 0; i < 16 && text[i] != '\0'; i++) row[i] = text[i];
    lcd.setCursor(0, r);
    lcd.print(row);
  }
}

void emitHello() { Serial.println(F("{\"evt\":\"hello\",\"fw\":\"0.1\"}")); }
void emitHeartbeat() { Serial.println(F("{\"evt\":\"hb\"}")); }

void emitError(const __FlashStringHelper* msg) {
  Serial.print(F("{\"evt\":\"error\",\"msg\":\""));
  Serial.print(msg);
  Serial.println(F("\"}"));
}

void emitPresence(uint8_t index) {
  Serial.print(F("{\"evt\":\"presence\",\"sensor\":"));
  Serial.print(index + 1);
  Serial.println('}');
}

void emitFinger(const __FlashStringHelper* result) {
  Serial.print(F("{\"evt\":\"finger\",\"result\":\""));
  Serial.print(result);
  Serial.println(F("\"}"));
}

void emitEnroll(const __FlashStringHelper* step, const __FlashStringHelper* msg = nullptr) {
  Serial.print(F("{\"evt\":\"enroll\",\"step\":\""));
  Serial.print(step);
  Serial.print(F("\",\"slot\":"));
  Serial.print(enrSlot);
  if (msg != nullptr) {
    Serial.print(F(",\"msg\":\""));
    Serial.print(msg);
    Serial.print('"');
  }
  Serial.println('}');
}

void emitDoor(bool open) {
  Serial.print(F("{\"evt\":\"door\",\"open\":"));
  Serial.print(open ? F("true") : F("false"));
  Serial.println('}');
}

// ================================================================= servo / puerta
void setDoor(bool open) {
  if (!servoAttached) {
    doorServo.attach(SERVO_PIN);
    servoAttached = true;
  }
  doorServo.write(open ? SERVO_OPEN_ANGLE : SERVO_CLOSED_ANGLE);
  servoDetachAt = millis() + SERVO_DETACH_MS;
  emitDoor(open);
}

void servoService() {
  if (servoAttached && (long)(millis() - servoDetachAt) >= 0) {
    doorServo.detach();
    servoAttached = false;
  }
}

// ================================================================= HC-SR04
int readCm(uint8_t trig, uint8_t echo) {
  digitalWrite(trig, LOW);
  delayMicroseconds(2);
  digitalWrite(trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig, LOW);
  unsigned long duration = pulseIn(echo, HIGH, 25000UL);  // ~4 m máx.
  if (duration == 0) return 999;
  return (int)(duration / 58UL);
}

void sensorsService() {
  unsigned long now = millis();
  if ((long)(now - nextSensorRead) < 0) return;
  nextSensorRead = now + 40;  // se alternan: cada sensor se lee cada ~80 ms

  uint8_t index = sensorTurn;
  sensorTurn ^= 1;
  Presence& s = ps[index];
  int cm = readCm(s.trig, s.echo);

  if (cm < s.threshold) {
    if (s.nearCount < 10) s.nearCount++;
    s.farCount = 0;
  } else if (cm > s.threshold + 10) {
    if (s.farCount < 10) s.farCount++;
    s.nearCount = 0;
  }

  if (!s.present && s.nearCount >= NEAR_READS) {
    s.present = true;
    s.lastEmit = now;
    emitPresence(index);
  } else if (s.present && s.farCount >= FAR_READS) {
    s.present = false;
  } else if (s.present && now - s.lastEmit >= PRESENCE_REPEAT_MS) {
    s.lastEmit = now;
    emitPresence(index);
  }
}

// ================================================================= botones
void buttonsService() {
  const uint8_t pins[2] = {BTN_ENTRANCE, BTN_WORKAREA};
  unsigned long now = millis();
  for (uint8_t i = 0; i < 2; i++) {
    bool down = digitalRead(pins[i]) == LOW;
    if (down && !btnWasDown[i] && now - btnLast[i] >= BUTTON_LOCKOUT_MS) {
      btnLast[i] = now;
      Serial.print(F("{\"evt\":\"assist\",\"where\":\""));
      Serial.print(i == 0 ? F("entrance") : F("work_area"));
      Serial.println(F("\"}"));
    }
    btnWasDown[i] = down;
  }
}

// ================================================================= huella
void authService() {
  if (!authActive) return;
  if ((long)(millis() - authDeadline) >= 0) {
    authActive = false;
    emitFinger(F("timeout"));
    return;
  }
  uint8_t p = finger.getImage();
  if (p != FINGERPRINT_OK) return;                // sin dedo (o lectura fallida): seguir esperando
  if (finger.image2Tz() != FINGERPRINT_OK) return;  // imagen de mala calidad: reintentar
  p = finger.fingerFastSearch();
  authActive = false;
  if (p == FINGERPRINT_OK) {
    Serial.print(F("{\"evt\":\"finger\",\"result\":\"match\",\"slot\":"));
    Serial.print(finger.fingerID);
    Serial.print(F(",\"score\":"));
    Serial.print(finger.confidence);
    Serial.println('}');
  } else {
    emitFinger(F("nomatch"));
  }
}

void enrollFail(const __FlashStringHelper* msg) {
  emitEnroll(F("fail"), msg);
  enr = ENR_NONE;
  lcdShow("Registro fallido", "");
}

void enrollService() {
  if (enr == ENR_NONE) return;
  if ((long)(millis() - enrDeadline) >= 0) {
    enrollFail(F("Tiempo agotado"));
    return;
  }
  switch (enr) {
    case ENR_PLACE1:
      if (finger.getImage() == FINGERPRINT_OK) {
        if (finger.image2Tz(1) != FINGERPRINT_OK) return;  // mala imagen: reintentar
        enr = ENR_REMOVE;
        enrDeadline = millis() + 20000UL;
        lcdShow("Retire el dedo", "");
        emitEnroll(F("remove"));
      }
      break;
    case ENR_REMOVE:
      if (finger.getImage() == FINGERPRINT_NOFINGER) {
        enr = ENR_PLACE2;
        enrDeadline = millis() + 20000UL;
        lcdShow("Mismo dedo", "otra vez");
        emitEnroll(F("place2"));
      }
      break;
    case ENR_PLACE2:
      if (finger.getImage() == FINGERPRINT_OK) {
        if (finger.image2Tz(2) != FINGERPRINT_OK) return;
        if (finger.createModel() != FINGERPRINT_OK) {
          enrollFail(F("Las huellas no coinciden"));
          return;
        }
        if (finger.storeModel(enrSlot) != FINGERPRINT_OK) {
          enrollFail(F("No se pudo guardar"));
          return;
        }
        emitEnroll(F("ok"));
        enr = ENR_NONE;
        lcdShow("Huella guardada", "");
      }
      break;
    default:
      break;
  }
}

void fingerprintCheck() {
  if (fpOk) return;
  if (millis() - lastFpCheck < 5000UL && lastFpCheck != 0) return;
  lastFpCheck = millis();
  fpSerial.listen();
  if (finger.verifyPassword()) {
    fpOk = true;
    finger.getTemplateCount();
  } else {
    emitError(F("Sensor de huella no responde"));
  }
}

// ================================================================= comandos de la PC
// Lector JSON mínimo (los comandos son planos y cortos; ArduinoJson no cabe cómodo en un UNO).
const char* findKey(const char* line, const char* key) {
  char pattern[20];
  snprintf(pattern, sizeof(pattern), "\"%s\":", key);
  const char* p = strstr(line, pattern);
  return p ? p + strlen(pattern) : nullptr;
}

bool jsonString(const char* line, const char* key, char* out, size_t outSize) {
  const char* p = findKey(line, key);
  if (!p || *p != '"') return false;
  p++;
  size_t i = 0;
  while (*p && *p != '"' && i < outSize - 1) out[i++] = *p++;
  out[i] = '\0';
  return true;
}

bool jsonLong(const char* line, const char* key, long* out) {
  const char* p = findKey(line, key);
  if (!p) return false;
  *out = strtol(p, nullptr, 10);
  return true;
}

bool jsonBool(const char* line, const char* key, bool* out) {
  const char* p = findKey(line, key);
  if (!p) return false;
  *out = strncmp(p, "true", 4) == 0;
  return true;
}

void handleLine(const char* line) {
  char cmd[16];
  if (!jsonString(line, "cmd", cmd, sizeof(cmd))) return;

  if (strcmp(cmd, "lcd") == 0) {
    char l1[20] = "", l2[20] = "";
    jsonString(line, "l1", l1, sizeof(l1));
    jsonString(line, "l2", l2, sizeof(l2));
    if (enr == ENR_NONE) lcdShow(l1, l2);   // durante el registro el UNO maneja su propio texto
  } else if (strcmp(cmd, "door") == 0) {
    bool open = false;
    if (jsonBool(line, "open", &open)) setDoor(open);
  } else if (strcmp(cmd, "auth_start") == 0) {
    long timeoutMs = 15000;
    jsonLong(line, "timeout_ms", &timeoutMs);
    if (enr != ENR_NONE) return;
    if (!fpOk) {
      emitError(F("Sensor de huella no responde"));
      emitFinger(F("timeout"));
      return;
    }
    fpSerial.listen();
    authActive = true;
    authDeadline = millis() + (unsigned long)timeoutMs;
  } else if (strcmp(cmd, "auth_cancel") == 0) {
    authActive = false;
  } else if (strcmp(cmd, "enroll") == 0) {
    long slot = 0;
    if (!jsonLong(line, "slot", &slot) || slot < 1 || slot > 250) return;
    if (!fpOk) {
      enrSlot = (uint8_t)slot;
      enrollFail(F("Sensor de huella no responde"));
      return;
    }
    authActive = false;
    enrSlot = (uint8_t)slot;
    enr = ENR_PLACE1;
    enrDeadline = millis() + 30000UL;
    lcdShow("Registro huella", "Ponga el dedo");
    emitEnroll(F("place1"));
  } else if (strcmp(cmd, "enroll_cancel") == 0) {
    enr = ENR_NONE;
  } else if (strcmp(cmd, "delete") == 0) {
    long slot = 0;
    if (!jsonLong(line, "slot", &slot) || slot < 1) return;
    bool ok = fpOk && finger.deleteModel((uint16_t)slot) == FINGERPRINT_OK;
    Serial.print(F("{\"evt\":\"deleted\",\"slot\":"));
    Serial.print(slot);
    Serial.print(F(",\"ok\":"));
    Serial.print(ok ? F("true") : F("false"));
    Serial.println('}');
  } else if (strcmp(cmd, "cfg") == 0) {
    long th1, th2;
    if (jsonLong(line, "th1", &th1) && th1 >= 10 && th1 <= 300) ps[0].threshold = (int)th1;
    if (jsonLong(line, "th2", &th2) && th2 >= 10 && th2 <= 300) ps[1].threshold = (int)th2;
  }
}

void serialService() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      if (lineLen > 0) handleLine(lineBuf);
      lineLen = 0;
    } else if (c != '\r') {
      if (lineLen < sizeof(lineBuf) - 1) lineBuf[lineLen++] = c;
      else lineLen = 0;  // línea demasiado larga: descartar
    }
  }
}

// ================================================================= setup / loop
void setup() {
  pinMode(TRIG1, OUTPUT);
  pinMode(ECHO1, INPUT);
  pinMode(TRIG2, OUTPUT);
  pinMode(ECHO2, INPUT);
  pinMode(BTN_ENTRANCE, INPUT_PULLUP);
  pinMode(BTN_WORKAREA, INPUT_PULLUP);

  Serial.begin(115200);
  lcd.init();
  lcd.backlight();
  lcdShow("EPP Monitor", "Iniciando...");

  finger.begin(57600);          // velocidad por defecto del R307S
  setDoor(false);               // puerta cerrada al arrancar
  fingerprintCheck();
  emitHello();
  lcdShow("EPP Monitor", "Esperando PC...");
}

void loop() {
  serialService();
  sensorsService();
  authService();
  enrollService();
  buttonsService();
  servoService();
  fingerprintCheck();

  unsigned long now = millis();
  if (now - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = now;
    emitHeartbeat();
  }
}
