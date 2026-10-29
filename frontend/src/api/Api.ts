// Cliente HTTP del backend (contrato en docs/API.md).
export const API: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'
export const WS_URL = API.replace(/^http/, 'ws') + '/ws'

export interface Status {
  state: string
  device_online: boolean
  door_open: boolean
  inside_count: number
  inside_worker_ids: number[]
  camera_online: boolean
  vision_enabled: boolean
  vision_fps: number
  simulated_device: boolean
  open_assistance: number
}

export interface EppEvent {
  id: number
  ts: string
  level: 'info' | 'warning' | 'alarm'
  type: string
  message: string
  data: Record<string, any> | null
}

export interface Worker {
  id: number
  code: string | null
  name: string
  role: string | null
  active: boolean
  fingerprint_slot: number | null
  has_fingerprint: boolean
  inside: boolean
}

export interface Track {
  track_id: number
  worker_id: number | null
  name: string | null
  status: string
  missing: string[]
}

export interface AttendanceRow { id: number; worker_id: number; worker_name: string; worker_code: string | null; direction: 'IN' | 'OUT'; ts: string }
export interface AttendanceSummary { worker_id: number; worker_name: string; worker_code: string | null; first_in: string | null; last_out: string | null; inside: boolean }
export interface Violation { id: number; ts: string; worker_id: number | null; worker_name: string | null; track_id: number | null; missing: string; duration_s: number | null; has_snapshot: boolean }
export interface AccessAttempt { id: number; ts: string; worker_id: number | null; worker_name: string | null; direction?: string; result?: string; [k: string]: any }
export interface Assistance { id: number; ts?: string; source?: string; status: 'open' | 'attended'; [k: string]: any }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!res.ok) {
    let detail = `Error ${res.status}`
    try { detail = (await res.json()).detail ?? detail } catch { /* sin cuerpo JSON */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

const qs = (p: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  const out = s.toString()
  return out ? '?' + out : ''
}
const json = (body: unknown) => ({ body: JSON.stringify(body) })

export const api = {
  status: () => request<Status>('/api/status'),
  // /api/events devuelve `data` como texto JSON (el WS lo manda ya como objeto): se normaliza aquí.
  events: async (limit = 200) => {
    const rows = await request<(Omit<EppEvent, 'data'> & { data: string | Record<string, any> | null })[]>(
      '/api/events' + qs({ limit }))
    return rows.map((r) => {
      let data = r.data
      if (typeof data === 'string') { try { data = JSON.parse(data) } catch { data = null } }
      return { ...r, data: (data as Record<string, any> | null) ?? {} } as EppEvent
    })
  },
  tracks: () => request<{ tracks: Track[] }>('/api/tracks'),
  assignTrack: (track_id: number, worker_id: number) =>
    request('/api/tracks/assign', { method: 'POST', ...json({ track_id, worker_id }) }),
  door: (open: boolean) => request('/api/door', { method: 'POST', ...json({ open }) }),

  workers: () => request<Worker[]>('/api/workers'),
  createWorker: (w: { name: string; code?: string | null; role?: string | null }) =>
    request<Worker>('/api/workers', { method: 'POST', ...json(w) }),
  updateWorker: (id: number, w: Partial<{ name: string; code: string | null; role: string | null; active: boolean }>) =>
    request<Worker>(`/api/workers/${id}`, { method: 'PUT', ...json(w) }),
  deleteWorker: (id: number) => request<void>(`/api/workers/${id}`, { method: 'DELETE' }),
  enrollFingerprint: (id: number) => request(`/api/workers/${id}/fingerprint`, { method: 'POST' }),
  deleteFingerprint: (id: number) => request(`/api/workers/${id}/fingerprint`, { method: 'DELETE' }),
  cancelEnroll: () => request('/api/enroll/cancel', { method: 'POST' }),

  attendance: (p: { date_from?: string; date_to?: string }) => request<AttendanceRow[]>('/api/attendance' + qs(p)),
  attendanceSummary: (p: { date_from?: string; date_to?: string }) =>
    request<AttendanceSummary[]>('/api/attendance/summary' + qs(p)),
  violations: (p: { date_from?: string; date_to?: string }) => request<Violation[]>('/api/violations' + qs(p)),
  accessAttempts: (p: { date_from?: string; date_to?: string }) => request<AccessAttempt[]>('/api/access-attempts' + qs(p)),
  assistance: (status?: 'open' | 'attended') => request<Assistance[]>('/api/assistance' + qs({ status })),
  attendAssistance: (id: number) => request(`/api/assistance/${id}/attend`, { method: 'POST' }),

  snapshotUrl: (violationId: number) => `${API}/api/violations/${violationId}/snapshot`,
  csvUrl: (kind: 'attendance' | 'violations', p: { date_from?: string; date_to?: string }) =>
    `${API}/api/reports/${kind}.csv` + qs(p),
}