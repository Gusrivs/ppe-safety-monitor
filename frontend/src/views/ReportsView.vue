<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import {
  api, type AccessAttempt, type Assistance, type AttendanceRow, type AttendanceSummary, type Violation,
} from '../api/Api'

type Tab = 'summary' | 'attendance' | 'violations' | 'attempts' | 'assistance'
const today = () => new Date().toLocaleDateString('en-CA') // AAAA-MM-DD en hora local

const tab = ref<Tab>('summary')
const from = ref(today())
const to = ref(today())
const loading = ref(false)
const error = ref('')
const photo = ref<Violation | null>(null)

const summary = ref<AttendanceSummary[]>([])
const attendance = ref<AttendanceRow[]>([])
const violations = ref<Violation[]>([])
const attempts = ref<AccessAttempt[]>([])
const assistance = ref<Assistance[]>([])

const TABS: [Tab, string][] = [
  ['summary', 'Asistencia por trabajador'], ['attendance', 'Entradas y salidas'],
  ['violations', 'Infracciones de EPP'], ['attempts', 'Intentos de acceso'], ['assistance', 'Asistencia técnica'],
]
const RESULT: Record<string, string> = {
  granted: 'Concedido', no_match: 'Huella no reconocida', intruder: 'Intruso', timeout: 'Tiempo agotado',
  already_inside: 'Ya estaba dentro', not_inside: 'No figuraba dentro', no_crossing: 'No cruzó',
}
const PPE: Record<string, string> = { helmet: 'casco', vest: 'chaleco' }
const missing = (m: string) => m.split(',').map((x) => PPE[x] ?? x).join(' y ')
const SOURCE: Record<string, string> = { entrance: 'Entrada', work_area: 'Área de trabajo', gui: 'Interfaz' }
const hm = (ts: string | null) => (ts ? ts.replace('T', ' ').slice(0, 19) : '—')

async function load() {
  loading.value = true
  error.value = ''
  const p = { date_from: from.value, date_to: to.value }
  try {
    if (tab.value === 'summary') summary.value = await api.attendanceSummary(p)
    else if (tab.value === 'attendance') attendance.value = await api.attendance(p)
    else if (tab.value === 'violations') violations.value = await api.violations(p)
    else if (tab.value === 'attempts') attempts.value = await api.accessAttempts(p)
    else assistance.value = await api.assistance()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch([tab, from, to], load)
</script>

<template>
  <main class="page">
    <section class="panel">
      <div class="row">
        <label>Desde<input type="date" v-model="from" :max="to" /></label>
        <label>Hasta<input type="date" v-model="to" :min="from" /></label>
        <button style="align-self:flex-end" @click="load">Actualizar</button>
        <span class="grow" />
        <a class="btn" style="align-self:flex-end" :href="api.csvUrl('attendance', { date_from: from, date_to: to })">⬇ CSV asistencia</a>
        <a class="btn" style="align-self:flex-end" :href="api.csvUrl('violations', { date_from: from, date_to: to })">⬇ CSV infracciones</a>
      </div>
    </section>

    <div class="tabs">
      <button v-for="[id, label] in TABS" :key="id" :class="{ active: tab === id }" @click="tab = id">{{ label }}</button>
    </div>

    <section class="panel">
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="loading" class="empty">Cargando…</p>

      <div v-else class="table-wrap">
        <template v-if="tab === 'summary'">
          <p v-if="!summary.length" class="empty">Sin asistencia en este rango.</p>
          <table v-else>
            <thead><tr><th>Código</th><th>Trabajador</th><th>Primera entrada</th><th>Última salida</th><th>Ahora</th></tr></thead>
            <tbody>
              <tr v-for="r in summary" :key="r.worker_id">
                <td>{{ r.worker_code ?? '—' }}</td><td><strong>{{ r.worker_name }}</strong></td>
                <td>{{ hm(r.first_in) }}</td><td>{{ hm(r.last_out) }}</td>
                <td><span class="badge" :class="r.inside ? 'warn' : 'off'">{{ r.inside ? 'Dentro' : 'Fuera' }}</span></td>
              </tr>
            </tbody>
          </table>
        </template>

        <template v-else-if="tab === 'attendance'">
          <p v-if="!attendance.length" class="empty">Sin movimientos en este rango.</p>
          <table v-else>
            <thead><tr><th>Fecha y hora</th><th>Trabajador</th><th>Movimiento</th></tr></thead>
            <tbody>
              <tr v-for="r in attendance" :key="r.id">
                <td>{{ hm(r.ts) }}</td><td>{{ r.worker_name }}</td>
                <td><span class="badge" :class="r.direction === 'IN' ? 'ok' : 'off'">{{ r.direction === 'IN' ? 'Entrada' : 'Salida' }}</span></td>
              </tr>
            </tbody>
          </table>
        </template>

        <template v-else-if="tab === 'violations'">
          <p v-if="!violations.length" class="empty">Sin infracciones en este rango.</p>
          <table v-else>
            <thead><tr><th>Fecha y hora</th><th>Trabajador</th><th>Faltó</th><th>Duración</th><th>Captura</th></tr></thead>
            <tbody>
              <tr v-for="v in violations" :key="v.id">
                <td>{{ hm(v.ts) }}</td>
                <td>{{ v.worker_name || `SIN ID${v.track_id ? ' (track ' + v.track_id + ')' : ''}` }}</td>
                <td><span class="badge bad">{{ missing(v.missing) }}</span></td>
                <td>{{ v.duration_s != null ? Math.round(v.duration_s) + ' s' : '—' }}</td>
                <td><button v-if="v.has_snapshot" class="small" @click="photo = v">Ver captura</button><span v-else class="muted">—</span></td>
              </tr>
            </tbody>
          </table>
        </template>

        <template v-else-if="tab === 'attempts'">
          <p v-if="!attempts.length" class="empty">Sin intentos de acceso en este rango.</p>
          <table v-else>
            <thead><tr><th>Fecha y hora</th><th>Sentido</th><th>Trabajador</th><th>Resultado</th><th>Intento</th></tr></thead>
            <tbody>
              <tr v-for="a in attempts" :key="a.id">
                <td>{{ hm(a.ts) }}</td><td>{{ a.direction === 'IN' ? 'Entrada' : 'Salida' }}</td>
                <td>{{ a.worker_name ?? '—' }}</td>
                <td><span class="badge" :class="a.result === 'granted' ? 'ok' : a.result === 'intruder' ? 'bad' : 'warn'">{{ RESULT[a.result ?? ''] ?? a.result }}</span></td>
                <td>{{ a.attempt_no ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </template>

        <template v-else>
          <p v-if="!assistance.length" class="empty">Sin solicitudes de asistencia técnica.</p>
          <table v-else>
            <thead><tr><th>#</th><th>Fecha y hora</th><th>Origen</th><th>Estado</th><th /></tr></thead>
            <tbody>
              <tr v-for="s in assistance" :key="s.id">
                <td>{{ s.id }}</td><td>{{ hm(s.ts ?? null) }}</td><td>{{ SOURCE[s.source ?? ''] ?? s.source }}</td>
                <td><span class="badge" :class="s.status === 'open' ? 'bad' : 'ok'">{{ s.status === 'open' ? 'Pendiente' : 'Atendida' }}</span></td>
                <td><button v-if="s.status === 'open'" class="small primary" @click="api.attendAssistance(s.id).then(load)">Atender</button></td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </section>

    <div v-if="photo" class="modal" @click.self="photo = null">
      <div class="panel dialog">
        <header>
          <h2>{{ photo.worker_name || 'SIN ID' }} · sin {{ missing(photo.missing) }}</h2>
          <button class="small" @click="photo = null">Cerrar</button>
        </header>
        <p class="muted">{{ hm(photo.ts) }}</p>
        <img :src="api.snapshotUrl(photo.id)" alt="Captura de la infracción" />
      </div>
    </div>
  </main>
</template>

<style scoped>
.tabs { display: flex; gap: .4rem; margin: 1rem 0 .75rem; flex-wrap: wrap; }
.tabs button.active { background: var(--accent); color: #1a1200; border-color: var(--accent); font-weight: 600; }
.modal { position: fixed; inset: 0; background: rgba(0,0,0,.7); display: grid; place-items: center; z-index: 50; }
.dialog { width: min(900px, 94vw); max-height: 92vh; overflow: auto; }
.dialog img { width: 100%; border-radius: 8px; display: block; }
</style>