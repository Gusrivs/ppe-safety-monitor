
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, WS_URL, type EppEvent, type Status } from '../api/Api'

export interface EnrollState {
  active: boolean
  workerId: number | null
  step: string
  result: 'ok' | 'failed' | null
  message: string
}

const MAX_EVENTS = 300

export const useLiveStore = defineStore('live', () => {
  const status = ref<Status | null>(null)
  const events = ref<EppEvent[]>([])
  const connected = ref(false)
  const dismissed = ref<Set<number>>(new Set())
  const enroll = ref<EnrollState>({ active: false, workerId: null, step: '', result: null, message: '' })
  // Sube con cada evento de trabajadores/huellas: las vistas lo observan para recargar la lista.
  const workersTick = ref(0)

  let ws: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  let started = false

  const notifications = computed(() =>
    events.value.filter((e) => (e.level === 'warning' || e.level === 'alarm') && !dismissed.value.has(e.id)),
  )

  function pushEvent(e: EppEvent) {
    if (events.value.some((x) => x.id === e.id)) return
    events.value.unshift(e)
    if (events.value.length > MAX_EVENTS) events.value.length = MAX_EVENTS
    trackEnroll(e)
  }

  function trackEnroll(e: EppEvent) {
    switch (e.type) {
      case 'enroll_started':
        enroll.value = { active: true, workerId: e.data?.worker_id ?? null, step: 'start', result: null, message: e.message }
        break
      case 'enroll_step':
        enroll.value = { ...enroll.value, active: true, step: e.data?.step ?? '', message: e.message }
        break
      case 'enroll_ok':
      case 'enroll_failed':
        enroll.value = { ...enroll.value, active: false, result: e.type === 'enroll_ok' ? 'ok' : 'failed', message: e.message }
        workersTick.value++
        break
      case 'worker_deleted':
      case 'fingerprint_deleted':
        workersTick.value++
        break
    }
  }

  function resetEnroll() {
    enroll.value = { active: false, workerId: null, step: '', result: null, message: '' }
  }

  async function loadHistory() {
    try {
      const old = await api.events(MAX_EVENTS)
      const known = new Set(events.value.map((e) => e.id))
      events.value = [...events.value, ...old.filter((e) => !known.has(e.id))]
        .sort((a, b) => b.id - a.id)
        .slice(0, MAX_EVENTS)
    } catch { /* el backend aún no responde: el WS reintentará */ }
  }

  function connect() {
    clearTimeout(retry)
    ws = new WebSocket(WS_URL)
    ws.onopen = () => {
      connected.value = true
      loadHistory()
    }
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.kind === 'status') status.value = msg.data
      else if (msg.kind === 'event') pushEvent(msg.data)
    }
    ws.onclose = () => {
      connected.value = false
      retry = setTimeout(connect, 2000) // reconexión automática
    }
    ws.onerror = () => ws?.close()
  }

  /** Se llama una sola vez (desde App.vue). */
  function start() {
    if (started) return
    started = true
    connect()
  }

  function dismiss(id: number) {
    dismissed.value = new Set(dismissed.value).add(id)
  }

  async function attendAssistance(e: EppEvent) {
    const id = e.data?.request_id
    if (id != null) await api.attendAssistance(id)
    dismiss(e.id)
  }

  return { status, events, connected, notifications, enroll, workersTick, start, dismiss, attendAssistance, resetEnroll }
})