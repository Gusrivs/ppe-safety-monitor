# Protocolo PC ⇄ Arduino UNO

USB serial, **115200 baudios**, una línea JSON por mensaje terminada en `\n`. Por el puerto solo
deben circular líneas JSON (nada de `Serial.print` de depuración). Texto del LCD: ASCII, 16
caracteres por línea (el backend ya quita tildes y recorta).

## Arduino → PC (eventos)

| Evento | Cuándo |
|---|---|
| `{"evt":"hello","fw":"0.1"}` | Al arrancar |
| `{"evt":"hb"}` | Latido cada 2 s |
| `{"evt":"presence","sensor":1}` / `2` | Un HC-SR04 detecta a alguien (3 lecturas seguidas bajo el umbral). Se repite cada 3 s mientras siga ahí |
| `{"evt":"finger","result":"match","slot":3,"score":120}` | Huella reconocida |
| `{"evt":"finger","result":"nomatch"}` | Huella no reconocida |
| `{"evt":"finger","result":"timeout"}` | Nadie puso el dedo en el tiempo dado |
| `{"evt":"enroll","step":"place1"\|"remove"\|"place2"\|"ok"\|"fail","slot":3,"msg":"..."}` | Progreso del registro de huella |
| `{"evt":"deleted","slot":3,"ok":true}` | Huella borrada del sensor |
| `{"evt":"door","open":true}` | La puerta (servo) cambió |
| `{"evt":"assist","where":"entrance"\|"work_area"}` | Botón de Asistencia Técnica |
| `{"evt":"error","msg":"..."}` | Problema (p. ej. sensor de huella sin respuesta) |

## PC → Arduino (comandos)

| Comando | Efecto |
|---|---|
| `{"cmd":"lcd","l1":"Hola","l2":"mundo"}` | Escribe en el LCD |
| `{"cmd":"door","open":true}` | Abre/cierra el servo |
| `{"cmd":"auth_start","timeout_ms":15000}` | Empieza a esperar un dedo |
| `{"cmd":"auth_cancel"}` | Deja de esperar |
| `{"cmd":"enroll","slot":3}` | Registra una huella nueva (2 pasadas del dedo) en esa ranura |
| `{"cmd":"enroll_cancel"}` | Cancela el registro |
| `{"cmd":"delete","slot":3}` | Borra la plantilla de la ranura |
| `{"cmd":"cfg","th1":80,"th2":80}` | Umbrales de presencia en cm (10–300) |

Probar a mano (Linux): `python -m serial.tools.miniterm /dev/ttyACM0 115200` y escribir, p. ej.,
`{"cmd":"lcd","l1":"Hola","l2":"Gus"}`.
