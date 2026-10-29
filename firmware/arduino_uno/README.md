# Firmware del Arduino UNO

Sketch: `epp_access/epp_access.ino`. Protocolo: `docs/PROTOCOLO_SERIAL.md`.

> Se comprobó que el sketch compila a nivel de sintaxis con librerías simuladas, pero **no se ha
> probado en el hardware real**. Prueba cada pieza por separado (abajo) antes de integrar.

## Librerías (Arduino IDE → Administrar bibliotecas)

- **Adafruit Fingerprint Sensor Library**
- **LiquidCrystal I2C** (Frank de Brabander)
- Servo (incluida)

Placa: *Arduino Uno*. Velocidad del monitor serie: 115200.

## Conexiones

| Componente | Pin del UNO | Notas |
|---|---|---|
| HC-SR04 #1 (fila / entrada) | TRIG → D4, ECHO → D5, VCC 5V, GND | El ECHO de 5V lo tolera el UNO |
| HC-SR04 #2 (interior) | TRIG → D6, ECHO → D7, VCC 5V, GND | Apuntar a la zona de la puerta |
| R307S huella | **TX del sensor → D2**; **RX del sensor ← D3 con divisor de voltaje**; GND | Alimentación: 3.3V (lo probaste así) |
| LCD 16x2 I2C | SDA → A4, SCL → A5, VCC 5V, GND | Dirección 0x27 (si no enciende, 0x3F) |
| Servo SG90 | Señal → D9, 5V, GND | Ver nota de energía |
| Pulsador asistencia (entrada) | D10 ↔ GND | `INPUT_PULLUP`, sin resistencia externa |
| Pulsador asistencia (área de trabajo) | D11 ↔ GND | idem |

**Divisor para D3 → RX del R307S** (el TX del UNO es 5V y la lógica del sensor es 3.3V):
D3 → resistencia 1 kΩ → RX del sensor, y desde ese punto una 2 kΩ a GND (≈ 3.3V).
El TX del sensor al D2 va directo.

**Energía:** el pin de 3.3V del UNO da poca corriente (~50 mA). Si el sensor de huella falla al
capturar o el UNO se reinicia, revisa el datasheet de tu módulo (algunos R307 piden 3.6–6V) y
aliméntalo desde 5V (manteniendo el divisor en la línea D3). El SG90 puede consumir picos de
varios cientos de mA: si el UNO se reinicia al mover la puerta, usa una fuente de 5V aparte
para el servo (con GND común) y un capacitor de 470 µF entre 5V y GND del servo.

## Pruebas por piezas (Monitor Serie, 115200, "Nueva línea")

1. Arranque: debe salir `{"evt":"hello","fw":"0.1"}` y luego `{"evt":"hb"}` cada 2 s.
2. LCD: `{"cmd":"lcd","l1":"Hola","l2":"Gus"}`
3. Servo: `{"cmd":"door","open":true}` y `{"cmd":"door","open":false}` (ajusta `SERVO_OPEN_ANGLE` si hace falta)
4. Sensores: acerca la mano a cada HC-SR04 → `{"evt":"presence","sensor":1}` / `2`
   (umbral 80 cm: `{"cmd":"cfg","th1":50,"th2":50}`)
5. Huella: registra con `{"cmd":"enroll","slot":1}`, luego `{"cmd":"auth_start","timeout_ms":10000}` y pon el dedo
6. Botones: pulsar → `{"evt":"assist","where":"entrance"}` / `work_area`

Si el sensor de huella no responde verás `{"evt":"error","msg":"Sensor de huella no responde"}`:
revisa TX/RX (no cruzados al revés), alimentación y que el baudrate sea 57600 (el de fábrica).
