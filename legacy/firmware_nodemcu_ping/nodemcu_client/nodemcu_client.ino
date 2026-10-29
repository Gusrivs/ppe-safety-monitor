#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>

#include "secrets.h"

const String EVENT_URL = String("http://") + SERVER_HOST + ":" + String(SERVER_PORT) + "/api/event";
const unsigned long PING_INTERVAL_MS = 10000;
unsigned long lastPingMs = 0;

bool connectToWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  Serial.printf("Conectando a Wi-Fi: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  const unsigned long startedAt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startedAt < 20000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("No se pudo conectar a Wi-Fi; se reintentará.");
    return false;
  }

  Serial.print("Wi-Fi conectado. IP del NodeMCU: ");
  Serial.println(WiFi.localIP());
  return true;
}

void sendPing() {
  if (!connectToWiFi()) {
    return;
  }

  WiFiClient client;
  HTTPClient http;
  if (!http.begin(client, EVENT_URL)) {
    Serial.println("No se pudo iniciar la petición HTTP.");
    return;
  }

  http.addHeader("Content-Type", "application/json");
  const int statusCode = http.POST("{\"event\":\"ping\",\"device\":\"nodemcu-esp8266\"}");
  if (statusCode > 0) {
    Serial.printf("Respuesta HTTP: %d\n", statusCode);
    Serial.println(http.getString());
  } else {
    Serial.printf("Error HTTP: %s\n", http.errorToString(statusCode).c_str());
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("\nCliente de comunicación EPP iniciado.");
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  connectToWiFi();
  sendPing();
  lastPingMs = millis();
}

void loop() {
  if (millis() - lastPingMs >= PING_INTERVAL_MS) {
    sendPing();
    lastPingMs = millis();
  }
  delay(50);
}
