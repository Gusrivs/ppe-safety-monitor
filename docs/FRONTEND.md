# Dónde y cómo crear el proyecto Vue

**Ubicación: `frontend/`, en la raíz del proyecto, junto a `backend/`.** No lo metas dentro de
`backend/` (son dos programas distintos que solo hablan por la API).

```bash
# desde la raíz de proyecto-epp/
npm create vue@latest frontend
#   TypeScript: Sí · Router: Sí · Pinia: Sí · Vitest/ESLint: opcional
cd frontend && npm install && npm run dev        # http://localhost:5173
```

El backend ya permite CORS desde `localhost:5173`, así que durante el desarrollo corres **dos
terminales**: `uvicorn` (backend, puerto 8000) y `npm run dev` (Vue, puerto 5173).

Variable de entorno en `frontend/.env`: `VITE_API_BASE=http://localhost:8000`

## Pantallas (según lo planeado)

1. **Panel principal** (`/`): video en vivo `<img :src="`${API}/video`">`, estado (Arduino, cámara, puerta,
   personas dentro), **log** de eventos y recuadro de **notificaciones** (eventos `warning`/`alarm`, botón
   "atender" en asistencia técnica).
2. **Trabajadores** (`/workers`): tabla + formulario (crear/editar/eliminar) y botón "Registrar huella" que
   muestra el progreso (`enroll_step` → `enroll_ok`).
3. **Reportes** (`/reports`): asistencia por día, infracciones con su captura, botones de descarga CSV.

## Tiempo real con WebSocket (esqueleto)

```ts
// src/stores/live.ts
const ws = new WebSocket(`${API.replace('http', 'ws')}/ws`)
ws.onmessage = (m) => {
  const msg = JSON.parse(m.data)
  if (msg.kind === 'status') status.value = msg.data
  else events.value.unshift(msg.data)          // msg.data = {id, ts, level, type, message, data}
}
// reconexión: vuelve a crear el WebSocket en onclose tras 2 s
```

Contrato completo de rutas: `docs/API.md`.

## Un solo comando para la demo

`npm run build` genera `frontend/dist/`; si esa carpeta existe, el backend la sirve en
`http://localhost:8000/` (no necesitas dos terminales ni `npm run dev` el día de la presentación).
