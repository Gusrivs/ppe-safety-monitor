<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, type Worker } from '../api/Api'
import { useLiveStore } from '@/stores/live'

const live = useLiveStore()
const workers = ref<Worker[]>([])
const loading = ref(true)
const error = ref('')
const editingId = ref<number | null>(null)
const form = reactive({ name: '', code: '', role: '' })

const STEP_TEXT: Record<string, string> = {
  start: 'Preparando el sensor…',
  place1: 'Coloca el dedo en el sensor',
  remove: 'Retira el dedo',
  place2: 'Coloca el MISMO dedo otra vez',
}
const stepText = computed(() => STEP_TEXT[live.enroll.step] ?? live.enroll.message)
const showEnroll = computed(() => live.enroll.active || live.enroll.result !== null)
const enrollWorker = computed(() => workers.value.find((w) => w.id === live.enroll.workerId)?.name ?? '')
const busy = computed(() => !!live.status && live.status.state.toLowerCase() !== 'idle')

async function load() {
  try {
    workers.value = await api.workers()
    error.value = ''
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function resetForm() {
  editingId.value = null
  Object.assign(form, { name: '', code: '', role: '' })
}
function edit(w: Worker) {
  editingId.value = w.id
  Object.assign(form, { name: w.name, code: w.code ?? '', role: w.role ?? '' })
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function save() {
  error.value = ''
  const body = { name: form.name.trim(), code: form.code.trim() || null, role: form.role.trim() || null }
  if (!body.name) { error.value = 'El nombre es obligatorio'; return }
  try {
    if (editingId.value == null) await api.createWorker(body)
    else await api.updateWorker(editingId.value, body)
    resetForm()
    await load()
  } catch (e) {
    error.value = (e as Error).message
  }
}

async function remove(w: Worker) {
  if (!confirm(`¿Eliminar a ${w.name}? Se borra su huella del sensor; el historial se conserva.`)) return
  error.value = ''
  try { await api.deleteWorker(w.id); await load() } catch (e) { error.value = (e as Error).message }
}

async function enrollFp(w: Worker) {
  error.value = ''
  live.resetEnroll()
  try { await api.enrollFingerprint(w.id) } catch (e) { error.value = (e as Error).message }
}
async function deleteFp(w: Worker) {
  if (!confirm(`¿Borrar la huella de ${w.name}?`)) return
  error.value = ''
  try { await api.deleteFingerprint(w.id); await load() } catch (e) { error.value = (e as Error).message }
}
async function cancelEnroll() {
  try { await api.cancelEnroll() } catch (e) { error.value = (e as Error).message }
  live.resetEnroll()
}

onMounted(load)
// Recarga la lista cuando termina un registro de huella o se borra algo.
watch(() => live.workersTick, load)
</script>

<template>
  <main class="page">
    <section class="panel">
      <header><h2>{{ editingId == null ? 'Nuevo trabajador' : 'Editar trabajador' }}</h2></header>
      <form class="row" @submit.prevent="save">
        <label class="grow">Nombre *<input v-model="form.name" placeholder="Ana Martínez" required /></label>
        <label>Código<input v-model="form.code" placeholder="T-001" /></label>
        <label>Cargo<input v-model="form.role" placeholder="Albañil" /></label>
        <div class="row" style="align-self:flex-end">
          <button class="primary" type="submit">{{ editingId == null ? 'Agregar' : 'Guardar cambios' }}</button>
          <button v-if="editingId != null" type="button" @click="resetForm">Cancelar</button>
        </div>
      </form>
      <p v-if="error" class="error">{{ error }}</p>
    </section>

    <section class="panel" style="margin-top:1rem">
      <header>
        <h2>Trabajadores</h2>
        <span class="muted">{{ workers.length }} registrados</span>
      </header>
      <p v-if="loading" class="empty">Cargando…</p>
      <p v-else-if="!workers.length" class="empty">Aún no hay trabajadores. Agrega el primero arriba.</p>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr><th>Código</th><th>Nombre</th><th>Cargo</th><th>Huella</th><th>Estado</th><th /></tr>
          </thead>
          <tbody>
            <tr v-for="w in workers" :key="w.id">
              <td>{{ w.code ?? '—' }}</td>
              <td><strong>{{ w.name }}</strong></td>
              <td>{{ w.role ?? '—' }}</td>
              <td>
                <span class="badge" :class="w.has_fingerprint ? 'ok' : 'off'">
                  {{ w.has_fingerprint ? `Ranura ${w.fingerprint_slot}` : 'Sin huella' }}
                </span>
              </td>
              <td>
                <span class="badge" :class="w.inside ? 'warn' : 'off'">{{ w.inside ? 'Dentro' : 'Fuera' }}</span>
                <span v-if="!w.active" class="badge bad" style="margin-left:.3rem">Inactivo</span>
              </td>
              <td>
                <div class="row actions">
                  <button class="small primary" :disabled="busy || !live.status?.device_online" @click="enrollFp(w)"
                    :title="!live.status?.device_online ? 'El Arduino no está conectado' : busy ? 'El sistema está ocupado' : ''">
                    {{ w.has_fingerprint ? 'Re-registrar huella' : 'Registrar huella' }}
                  </button>
                  <button v-if="w.has_fingerprint" class="small" :disabled="busy" @click="deleteFp(w)">Borrar huella</button>
                  <button class="small" @click="edit(w)">Editar</button>
                  <button class="small danger" @click="remove(w)">Eliminar</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="showEnroll" class="modal">
      <div class="dialog panel">
        <h2>Registro de huella</h2>
        <p class="muted">{{ enrollWorker }}</p>
        <template v-if="live.enroll.active">
          <p class="big">{{ stepText }}</p>
          <div class="progress"><span :class="{ on: ['place1','remove','place2'].includes(live.enroll.step) }" />
            <span :class="{ on: ['remove','place2'].includes(live.enroll.step) }" />
            <span :class="{ on: live.enroll.step === 'place2' }" /></div>
          <button @click="cancelEnroll">Cancelar registro</button>
        </template>
        <template v-else>
          <p class="big" :class="live.enroll.result === 'ok' ? 'okc' : 'error'">
            {{ live.enroll.result === 'ok' ? '✔ Huella registrada' : '✖ ' + live.enroll.message }}
          </p>
          <button class="primary" @click="live.resetEnroll()">Cerrar</button>
        </template>
      </div>
    </div>
  </main>
</template>

<style scoped>
form label { min-width: 150px; }
.actions { flex-wrap: wrap; }
.modal { position: fixed; inset: 0; background: rgba(0,0,0,.65); display: grid; place-items: center; z-index: 50; }
.dialog { width: min(420px, 92vw); text-align: center; display: grid; gap: .75rem; }
.big { font-size: 1.25rem; font-weight: 600; margin: .5rem 0; }
.okc { color: var(--ok); }
.progress { display: flex; gap: .4rem; justify-content: center; }
.progress span { width: 2.5rem; height: .35rem; border-radius: 4px; background: var(--line); }
.progress span.on { background: var(--accent); }
</style>