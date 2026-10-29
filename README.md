# Sistema de monitoreo automatizado de EPP y seguridad industrial

Prototipo académico (Arquitectura de Computadoras, UES-FMOcc). Verifica que cada trabajador use
**casco y chaleco** dentro de una zona de construcción, identifica a cada persona con **huella
dactilar** al entrar y registra **asistencia**, infracciones y solicitudes de asistencia técnica.

```
 Fila de trabajadores
        │
  [HC-SR04 #1] → [R307S huella + LCD 16x2] → [servo SG90 puerta] → [HC-SR04 #2]      ┐
        ▲                                                                            │ Arduino UNO
   [pulsador asistencia]                                       [pulsador asistencia] ┘  (USB serial, JSON)
                                   │
                                   ▼
                         PC (Python / FastAPI)  ◄──── celular con IP Webcam (video)
          ┌────────────────────────┼──────────────────────────┐
     Control de acceso       Visión (YOLO + tracker)      SQLite + capturas
     (máquina de estados)    casco/chaleco + identidad     (todo local)
          └────────────────────────┼──────────────────────────┘
                                   ▼
                       API REST + WebSocket + video MJPEG
                                   ▼
                        Interfaz Vue (frontend/, por crear)
```

## Estructura del proyecto

| Carpeta | Qué contiene |
|---|---|
| `backend/` | **El cerebro** (Python/FastAPI): acceso, visión, base de datos, API. |
| `backend/app/access/` | Máquina de estados de entrada/salida (intentos, tiempos, reglas). |
| `backend/app/device/` | Comunicación con el Arduino (serial real y **simulador** sin hardware). |
| `backend/app/vision/` | Cámara, YOLO, reglas casco/chaleco, tracker, identidad, infracciones de 30 s. |
| `backend/app/api/` | Rutas HTTP/WebSocket que consumirá Vue. |
| `backend/tests/` | Pruebas automáticas (`pytest`). |
| `backend/tools/` | Probar la cámara y probar la IA sobre un video. |
| `firmware/arduino_uno/` | Sketch del Arduino UNO y guía de conexiones. |
| `ml/` | Entrenamiento: fotogramas, etiquetado, dataset, entrenar, evaluar. |
| `frontend/` | **Aún no existe: aquí se crea el proyecto Vue** (`npm create vue@latest frontend`, ver `docs/FRONTEND.md`). |
| `config/` | `config.example.yaml` → cópialo a `config.yaml`. |
| `data/` | Se genera sola: base de datos, capturas de infracciones, grabaciones. |
| `models/` | Pesos `.pt` de YOLO (no se suben a Git). |
| `docs/` | `ARQUITECTURA.md`, `PROTOCOLO_SERIAL.md`, `API.md`, `FRONTEND.md` y el perfil del proyecto (PDF). |
| `legacy/` | Prueba inicial del ESP8266 (HTTP). Ya no se usa; se conserva como referencia. |
| `assets/` | Imágenes de prueba. |

## Puesta en marcha (sin hardware, en 5 minutos)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt        # (ultralytics es pesado; puedes omitirlo al inicio)
cp config/config.example.yaml config/config.yaml    # ya viene con device.simulate: true
cd backend
python -m pytest -q                                 # las pruebas deben pasar
python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

- Documentación interactiva de la API: <http://localhost:8000/docs>
- Video en vivo: <http://localhost:8000/video> (si no hay cámara muestra "Sin señal")
- Con el **simulador** puedes recorrer todo el flujo desde `/docs` → `POST /api/sim/event`
  (por ejemplo `{"event":{"evt":"presence","sensor":1}}`). Ver `docs/ARQUITECTURA.md`.

## Pasar a hardware real

1. Arma el circuito y carga el sketch: `firmware/arduino_uno/README.md`.
2. En `config/config.yaml`: `device.simulate: false` y `device.port: /dev/ttyACM0`
   (en Linux agrega tu usuario al grupo `dialout`: `sudo usermod -aG dialout $USER` y reinicia sesión).
3. Cámara: instala **IP Webcam** en el celular, pon su URL en `camera.url` y prueba con
   `python backend/tools/test_camera.py`.
4. Entrena el detector con tus videos (`ml/README.md`) y activa `vision.enabled: true`.

## Estado actual

Funciona y está probado con pruebas automáticas: base de datos, máquina de estados de acceso
(3 intentos, intruso, cruce, salida, enrolamiento, asistencia técnica), API/WebSocket/CSV,
simulador, monitor de infracciones (30 s / enfriamiento 1 min), traspaso de ID huella → cámara,
y el flujo de datos propios (video → fotogramas → dataset train/val/test).

**Aún sin probar con equipo real** (no se pudo desde el entorno de desarrollo): firmware en el
UNO, cámara real, y los modelos YOLO. Aparte, falta el frontend Vue y el entrenamiento con tus
videos. Límites conocidos en `docs/ARQUITECTURA.md`.
