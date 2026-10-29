# API del backend (contrato para el frontend Vue)

Base: `http://localhost:8000` · Documentación interactiva autogenerada: `/docs` · Sin autenticación (demo local).
Fechas: `AAAA-MM-DD` (por defecto, hoy). Errores: JSON `{"detail": "mensaje"}`.

## Estado y video

| Método y ruta | Descripción |
|---|---|
| `GET /api/status` | `state`, `device_online`, `door_open`, `inside_count`, `inside_worker_ids`, `camera_online`, `vision_enabled`, `vision_fps`, `simulated_device`, `open_assistance` |
| `GET /video` | Video en vivo MJPEG: `<img src="http://localhost:8000/video">` |
| `GET /api/snapshot.jpg` | Último fotograma anotado |
| `GET /api/tracks` | Personas vistas ahora: `track_id`, `worker_id`, `name`, `status`, `missing`, `box` (0–1) |
| `POST /api/tracks/assign` | `{"track_id":12,"worker_id":3}` asigna a mano un trabajador a un track "SIN ID" |
| `POST /api/door` | `{"open":true}` apertura manual (se cierra sola a los 8 s) |
| `WS /ws` | Tiempo real (abajo) |

## Trabajadores (CRUD y huella)

| Método y ruta | Descripción |
|---|---|
| `GET /api/workers` | Lista con `inside` y `has_fingerprint` |
| `POST /api/workers` | `{"name":"Ana","code":"T-001","role":"Albañil"}` → 201 (409 si el código existe) |
| `GET/PUT/DELETE /api/workers/{id}` | Leer, editar (campos opcionales: `name`, `code`, `role`, `active`), eliminar (borra también la huella; conserva historial) |
| `POST /api/workers/{id}/fingerprint` | Inicia el registro de huella → 202. Seguir el progreso por WS (`enroll_step`, `enroll_ok`, `enroll_failed`). 409 si el sistema está ocupado o el Arduino desconectado |
| `DELETE /api/workers/{id}/fingerprint` | Borra la huella del sensor |
| `POST /api/enroll/cancel` | Cancela el registro en curso |

## Registros y reportes

| Ruta | Descripción |
|---|---|
| `GET /api/attendance?date_from=&date_to=&worker_id=&limit=` | Entradas/salidas |
| `GET /api/attendance/summary?date_from=&date_to=` | Por trabajador: `first_in`, `last_out`, `inside` |
| `GET /api/access-attempts` | Intentos de acceso (granted, no_match, intruder, timeout, already_inside, not_inside, no_crossing) |
| `GET /api/violations?date_from=&date_to=&worker_id=` | Infracciones de EPP (`worker_name` vacío = SIN ID, `missing`: `helmet`, `vest` o `helmet,vest`) |
| `GET /api/violations/{id}/snapshot` | Imagen JPEG de la captura |
| `GET /api/assistance?status=open` · `POST /api/assistance/{id}/attend` | Asistencia técnica |
| `GET /api/events?limit=100&level=alarm` | Log general (`info`, `warning`, `alarm`) |
| `GET /api/reports/attendance.csv` · `GET /api/reports/violations.csv` | CSV para Excel (con `date_from`/`date_to`) |

## WebSocket `/ws`

Mensajes `{"kind":"status","data":{...}}` (igual que `/api/status`, al conectar, tras cada evento y cada 2 s) y
`{"kind":"event","data":{"id","ts","level","type","message","data"}}`.

Tipos de evento (`type`): `system_started`, `device_online`, `device_offline`, `device_error`,
`auth_started`, `auth_failed`, `auth_aborted`, `access_granted`, `access_rejected`, `intruder_alert` (alarm),
`worker_entered`, `worker_exited`, `crossing_timeout`, `assistance_request`, `assistance_attended`,
`enroll_started`, `enroll_step`, `enroll_ok`, `enroll_failed`, `fingerprint_deleted`, `door_manual`,
`ppe_violation` (alarm), `ppe_resolved`, `identity_assigned`, `handoff_failed`, `vision_unavailable`, `worker_deleted`.

Sugerencia: el panel de **notificaciones** = eventos `warning`/`alarm`; el **log** = todos.

## Simulador (solo con `device.simulate: true`)

`POST /api/sim/event` `{"event":{"evt":"presence","sensor":1}}` · `GET /api/sim/state` → `lcd`, `door_open`.
