# Sistema de monitoreo automatizado de EPP y seguridad industrial

Primera etapa del prototipo: verificar comunicación HTTP/JSON entre un NodeMCU V3 (ESP8266) y una computadora Debian en la misma red Wi-Fi. El lector de huellas, los sensores HC-SR04, YOLO y la base de datos se integrarán en etapas posteriores.

## Estructura

```text
server/server.py                    Servidor HTTP de Python
firmware/nodemcu/nodemcu_client/nodemcu_client.ino Cliente Wi-Fi para ESP8266
firmware/nodemcu/nodemcu_client/secrets.example.h  Plantilla local de configuración
```

## 1. Preparar Debian

Consulta la IP local de Debian con:

```bash
hostname -I
```

Si Debian usa UFW, permite conexiones desde la red local al puerto del servidor (reemplaza la subred por la de tu Wi-Fi):

```bash
sudo ufw allow from 192.168.1.0/24 to any port 8080 proto tcp
```

Inicia el servidor desde la raíz del proyecto:

```bash
python3 server/server.py
```

La API escucha en `0.0.0.0:8080`. Comprueba su estado desde Debian:

```bash
curl http://127.0.0.1:8080/health
```

## 2. Preparar Arduino IDE

1. Copia `firmware/nodemcu/nodemcu_client/secrets.example.h` como `firmware/nodemcu/nodemcu_client/secrets.h`.
2. Configura `WIFI_SSID`, `WIFI_PASSWORD`, `SERVER_HOST` (la IP de Debian) y `SERVER_PORT` en `secrets.h`.
3. Abre `firmware/nodemcu/nodemcu_client/nodemcu_client.ino` en Arduino IDE. El archivo `secrets.h` debe permanecer en la misma carpeta del sketch.
4. Selecciona la placa NodeMCU 1.0 (ESP-12E Module) y el puerto correspondiente, por ejemplo `/dev/ttyUSB0`; carga el sketch.
5. Abre el Monitor Serial a 115200 baudios.

El cliente manda un `ping` al iniciar y luego cada 10 segundos. En la consola de Debian debe aparecer `Evento recibido` y el Monitor Serial debe mostrar una respuesta HTTP 200.

## API inicial

`POST /api/event` acepta un objeto JSON. Para la prueba inicial:

```json
{"event":"ping","device":"nodemcu-esp8266"}
```

Eventos previstos para las siguientes etapas:

```json
{"event":"worker_identified","worker_id":4}
{"event":"crossing","direction":"IN"}
```

`direction` admite `IN` o `OUT`. El servidor valida estos formatos, pero todavía no mantiene estado de operario ni realiza inferencia o persistencia. Los JSON mal formados reciben HTTP 400 y los eventos con campos inválidos reciben HTTP 422.
