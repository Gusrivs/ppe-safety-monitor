<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, API, type Track, type Worker } from '../api/Api'
import { useLiveStore } from '@/stores/live'

const live = useLiveStore()
const tracks = ref<Track[]>([])
const workers = ref<Worker[]>([])
const error = ref('')
const videoFailed = ref(false)
const showAll = ref(true)
let poll: ReturnType<typeof setInterval> | undefined

const STATE_LABEL: Record<string, string> = {
  idle: 'En espera', entry_auth: 'Verificando entrada', entry_wait_cross: 'Esperando cruce (entrada)',
  exit_auth: 'Verificando salida', exit_wait_cross: 'Esperando cruce (salida)',
  closing: 'Cerrando puerta', denied: 'Acceso denegado', enrolling: 'Registrando huella',
}
const stateLabel = computed(() => {
  const s = live.status?.state
  return s ? STATE_LABEL[s.toLowerCase()] ?? s : '—'
})
const PPE: Record<string, string> = { helmet: 'casco', vest: 'chaleco' }
const statusBadge = (t: Track) =>
  t.status === 'compliant' ? ['ok', 'Cumple'] :
  t.status === 'not_detected' ? ['bad', 'Falta ' + (t.missing.map((m) => PPE[m] ?? m).join(' y ') || 'EPP')] :
  ['off', 'Indeterminado']

const log = computed(() => (showAll.value ? live.events : live.notifications).slice(0, 80))

async function refresh() {
  try {
    tracks.value = (await api.tracks()).tracks
  } catch { /* se ve en el banner global */ }
}
async function loadWorkers() {
  try { workers.value = (await api.workers()).filter((w) => w.active) } catch { /* idem */ }
}
async function assign(t: Track, workerId: string) {
  if (!workerId) return
  error.value = ''
  try { await api.assignTrack(t.track_id, Number(workerId)); await refresh() }
  catch (e) { error.value = (e as Error).message }
}
async function door(open: boolean) {
  error.value = ''
  try { await api.door(open) } catch (e) { error.value = (e as Error).message }
}
const time = (ts: string) => ts.slice(11, 19)

onMounted(() => { refresh(); loadWorkers(); poll = setInterval(refresh, 1000) })
onBeforeUnmount(() => clearInterval(poll))
</script>

<template>
  <main class="page grid">
    <section class="panel video">
      <header>
        <h2>Cámara en vivo</h2>
        <span class="muted">
          <template v-if="live.status?.vision_enabled">IA activa · {{ live.status.vision_fps }} fps</template>
          <template v-else>Solo video (IA desactivada)</template>
        </span>
      </header>
      <div class="frame">
        <img v-if="!videoFailed" :src="`${API}/video`" alt="Video en vivo" @error="videoFailed = true" />
        <div v-else class="novideo">
          <p>No se pudo abrir el video.</p>
          <button @click="videoFailed = false">Reintentar</button>
        </div>
        <div v-if="live.status && !live.status.camera_online" class="novideo overlay">Sin señal de la cámara</div>
      </div>
    </section>

    <aside class="side">
      <section class="panel">
        <header><h2>Estado del sistema</h2></header>
        <ul class="kv">
          <li><span>Arduino</span>
            <span class="badge" :class="live.status?.device_online ? 'ok' : 'bad'">{{ live.status?.device_online ? 'Conectado' : 'Desconectado' }}</span></li>
          <li><span>Cámara</span>
            <span class="badge" :class="live.status?.camera_online ? 'ok' : 'bad'">{{ live.status?.camera_online ? 'En línea' : 'Sin señal' }}</span></li>
          <li><span>Puerta</span>
            <span class="badge" :class="live.status?.door_open ? 'warn' : 'off'">{{ live.status?.door_open ? 'Abierta' : 'Cerrada' }}</span></li>
          <li><span>Control de acceso</span><strong>{{ stateLabel }}</strong></li>
          <li><span>Personas dentro</span><strong>{{ live.status?.inside_count ?? '—' }}</strong></li>
        </ul>
        <div class="row" style="margin-top:.75rem">
          <button @click="door(true)">Abrir puerta</button>
          <button @click="door(false)">Cerrar</button>
        </div>
        <p v-if="error" class="error">{{ error }}</p>
      </section>

      <section class="panel">
        <header><h2>Personas en cámara</h2><span class="muted">{{ tracks.length }}</span></header>
        <p v-if="!tracks.length" class="empty">Nadie en el encuadre.</p>
        <ul v-else class="tracks">
          <li v-for="t in tracks" :key="t.track_id">
            <div class="row">
              <strong class="grow">{{ t.name ?? `SIN ID (track ${t.track_id})` }}</strong>
              <span class="badge" :class="statusBadge(t)[0]">{{ statusBadge(t)[1] }}</span>
            </div>
            <select v-if="t.worker_id == null" @change="assign(t, ($event.target as HTMLSelectElement).value)">
              <option value="">Asignar trabajador…</option>
              <option v-for="w in workers" :key="w.id" :value="w.id">{{ w.name }}</option>
            </select>
          </li>
        </ul>
      </section>
    </aside>

    <section class="panel">
      <header>
        <h2>Notificaciones</h2>
        <span class="badge" :class="live.notifications.length ? 'bad' : 'off'">{{ live.notifications.length }}</span>
      </header>
      <p v-if="!live.notifications.length" class="empty">Sin alertas pendientes.</p>
      <ul class="notes">
        <li v-for="e in live.notifications.slice(0, 20)" :key="e.id" :class="e.level">
          <div class="grow">
            <strong>{{ e.message }}</strong>
            <div class="muted">{{ time(e.ts) }}</div>
          </div>
          <button v-if="e.type === 'assistance_request'" class="small primary" @click="live.attendAssistance(e)">Atender</button>
          <button class="small" @click="live.dismiss(e.id)">Descartar</button>
        </li>
      </ul>
    </section>

    <section class="panel">
      <header>
        <h2>Registro de eventos</h2>
        <label class="row" style="flex-direction:row;align-items:center">
          <input type="checkbox" v-model="showAll" /> Mostrar todos
        </label>
      </header>
      <p v-if="!log.length" class="empty">Sin eventos todavía.</p>
      <ul class="log">
        <li v-for="e in log" :key="e.id" :class="e.level">
          <span class="muted">{{ time(e.ts) }}</span>
          <span>{{ e.message }}</span>
        </li>
      </ul>
    </section>
  </main>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 1rem; align-items: start; }
.video { grid-row: span 1; }
.side { display: grid; gap: 1rem; }
.frame { position: relative; background: #000; border-radius: 8px; overflow: hidden; aspect-ratio: 16 / 9; }
.frame img { width: 100%; height: 100%; object-fit: contain; display: block; }
.novideo { position: absolute; inset: 0; display: grid; place-content: center; gap: .5rem; text-align: center; color: var(--muted); }
.novideo.overlay { background: rgba(0,0,0,.55); place-content: center; font-weight: 600; pointer-events: none; }
.kv { list-style: none; margin: 0; padding: 0; display: grid; gap: .45rem; }
.kv li { display: flex; justify-content: space-between; align-items: center; }
.kv li > span:first-child { color: var(--muted); }
.tracks, .notes, .log { list-style: none; margin: 0; padding: 0; }
.tracks li { padding: .5rem 0; border-bottom: 1px solid var(--line); display: grid; gap: .4rem; }
.notes li { display: flex; gap: .5rem; align-items: center; padding: .5rem .6rem; margin-bottom: .4rem;
  border-radius: 8px; border-left: 3px solid var(--warn); background: var(--panel-2); }
.notes li.alarm { border-left-color: var(--danger); background: color-mix(in srgb, var(--danger) 12%, var(--panel-2)); }
.log { max-height: 340px; overflow-y: auto; font-size: .88rem; }
.log li { display: flex; gap: .75rem; padding: .25rem 0; border-bottom: 1px solid var(--line); }
.log li.warning { color: var(--warn); }
.log li.alarm { color: var(--danger); font-weight: 600; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
</style>