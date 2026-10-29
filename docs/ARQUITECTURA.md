# Arquitectura y flujos

## Reparto de responsabilidades

| Pieza | Hace | NO hace |
|---|---|---|
| **Arduino UNO** | Lee 2 HC-SR04, huella, 2 botones; mueve el servo; escribe el LCD; envía eventos JSON | Decidir nada (intentos, tiempos, quién está dentro) |
| **Backend (PC)** | Toda la política y el estado; base de datos; IA; API | — |
| **Frontend Vue** | Mostrar y operar (video, logs, CRUD, reportes) | Lógica de negocio |

Ventaja: para cambiar una regla (p. ej. 5 intentos en vez de 3) solo editas `config.yaml`; el
firmware no se toca ni se vuelve a cargar.

## Flujo de entrada

```
IDLE ──sensor 1──► ENTRY_AUTH ──huella OK──► ENTRY_WAIT_CROSS ──sensor 2──► CLOSING ──► IDLE
                      │  ▲ (hasta 3 intentos)        │ 10 s sin sensor 2
                      │  └── nomatch                 └──► se descarta, IDLE (como si nunca se hubiera presentado)
                      └── 3 fallos ──► DENIED (LCD "VETE!!") ──► IDLE   + alerta de intruso
```

La **salida** es el espejo: sensor 2 → huella → puerta → el sensor 1 confirma. Mientras un
flujo está activo (incluido `CLOSING`) no se acepta al siguiente: así se cumple "completar un
trabajador antes de identificar al siguiente".

Reglas adicionales (en `access/controller.py`): quien ya está dentro no puede volver a entrar;
quien no figura dentro no puede salir; tras un intento abortado el mismo lado se ignora
`retrigger_cooldown_s` segundos; sin latidos del Arduino > 6 s → "dispositivo desconectado".

## Traspaso de identidad: huella → cámara

1. El sensor 2 confirma el cruce → el controlador llama `vision.handle_entered(worker_id)`.
2. `IdentityTracker` espera el **primer track nuevo** de YOLO que aparezca en `vision.entry_zone`
   (acepta tracks nacidos hasta `handoff_lookback_s` antes) y le asigna ese `worker_id`.
3. Mientras la cámara lo siga viendo, la etiqueta en pantalla es su nombre.
4. Si el tracker lo pierde o cambia de id, queda como **"SIN ID (track N)"**. Sus infracciones
   se registran igual (con `worker_id` vacío) y se revisan en el video grabado/captura. Desde la
   interfaz se puede corregir con `POST /api/tracks/assign`.
5. Al salir, `release_worker` deja de monitorear ese track.

## Infracciones de EPP

Por fotograma, cada persona queda `compliant`, `not_detected` (falta una pieza, persona de
tamaño fiable) o `indeterminate` (muy pequeña o ambigua). **Un fotograma `not_detected` no es
una infracción**: `ViolationMonitor` exige `violation_seconds` (30 s) continuos, tolera
fotogramas sueltos (se reinicia tras `compliance_reset_seconds` = 3 s cumpliendo) y aplica un
enfriamiento de `cooldown_seconds` (60 s) por trabajador. Al advertir guarda captura en
`data/captures/AAAA-MM-DD/`, una fila en `violations` y un evento `ppe_violation` por WebSocket.

## Base de datos (SQLite, `data/epp.db`)

`workers` (con `fingerprint_slot`), `attendance` (IN/OUT), `access_attempts` (granted, no_match,
intruder, timeout, already_inside, not_inside, no_crossing), `violations`, `assistance_requests`,
`events` (log general). Borrar un trabajador es "borrado lógico": se conserva su historial.

Hora: la PC pone el timestamp al recibir cada evento (no hace falta sincronizar relojes). Latidos
del Arduino cada 2 s detectan desconexiones; el puerto serial se reabre solo.

## Simulador (desarrollar sin hardware)

Con `device.simulate: true` el "Arduino" es un objeto Python. Recorrer el flujo desde `/docs`:

```
POST /api/workers {"name":"Ana"}                       → crea el trabajador (id 1)
POST /api/workers/1/fingerprint                         → registro simulado (en ~2 s queda con huella)
POST /api/sim/event {"event":{"evt":"presence","sensor":1}}
POST /api/sim/event {"event":{"evt":"finger","result":"match","slot":1}}
POST /api/sim/event {"event":{"evt":"presence","sensor":2}}     → Ana entró
GET  /api/sim/state                                     → LCD y puerta simulados
```

## Límites conocidos (para tu documento y para la demo)

- Si el tracker cambia el id de una persona, se pierde su nombre (queda "SIN ID") hasta
  asignarla a mano. Es el punto más frágil del diseño.
- El sensor 2 detecta "intención de salir" por presencia: alguien que trabaje justo al lado de la
  puerta puede iniciar intentos de salida; el enfriamiento lo mitiga pero no lo elimina. Coloca
  el HC-SR04 #2 apuntando a la zona de la puerta, no al área de trabajo.
- Los HC-SR04 dan falsos positivos: el firmware exige 3 lecturas seguidas; ajusta el umbral
  (`cfg th1/th2`, 80 cm por defecto).
- Sin autenticación en la API (demo local). No expongas el puerto 8000 a internet.
- La IA depende de la iluminación y la distancia; personas pequeñas en el encuadre salen
  `indeterminate`.
- Las plantillas de huella viven en el sensor: si lo cambias, hay que volver a registrarlas.
