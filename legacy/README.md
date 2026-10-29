# Legacy: prueba inicial del ESP8266 (HTTP)

Código de la primera prueba de comunicación (NodeMCU V3 → servidor HTTP en Debian, evento `ping`).
**Ya no se usa en el sistema real**: ahora el Arduino UNO se conecta por USB y habla JSON por serial
(`docs/PROTOCOLO_SERIAL.md`). Se conserva porque el ESP8266 queda como **mejora opcional**: su única
tarea sería reenviar por Wi-Fi las mismas líneas JSON del UNO, sin cambiar el backend.

- `server_http_esp/server.py`: receptor HTTP mínimo (`POST /api/event`).
- `firmware_nodemcu_ping/`: cliente Wi-Fi del ESP8266. Copia `secrets.example.h` como `secrets.h` (no se sube a Git).
