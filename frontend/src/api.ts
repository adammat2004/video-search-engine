// Typed wrappers around the FastAPI backend (see backend/app.py).

export type Shot = {
  row: number
  shot_id: string
  v3c_id: string
  n: number
  start_ms: number
  end_ms: number
  score: number
  title: string
  snippet: string
  next_shot?: Shot
}

export type Mode = 'visual' | 'speech' | 'fused' | 'temporal'
export type TaskType = 'KIS' | 'AVS'
export type Verdict = 'CORRECT' | 'WRONG' | 'INDETERMINATE' | 'UNDECIDABLE' | 'ERROR' | null

export type SubmitResult = {
  verdict: Verdict
  http_status: number
  description: string
  v3c_id: string
  start_ms: number
  end_ms: number
  shot_id?: string | null
  time?: string
}

export type DresStatus = {
  configured: boolean
  url: string
  api: string
  logged_in: boolean
  active?: { id: string; name: string }[]
  current_task?: { name: string; taskGroup: string; taskType: string; duration: number } | null
  error?: string
}

export type VideoInfo = { v3c_id: string; title: string; duration_ms: number; vimeo_url: string; shots: Shot[] }
export type Answer = { shot_id?: string; v3c_id?: string; start_ms?: number; end_ms?: number }
type Results = { results: Shot[]; count: number }

async function j<T>(p: Promise<Response>): Promise<T> {
  const r = await p
  if (!r.ok) {
    let msg = await r.text()
    try { msg = JSON.parse(msg).detail ?? msg } catch { /* plain text */ }
    throw new Error(`${r.status}: ${msg}`)
  }
  return r.json()
}

const post = (url: string, body: unknown) =>
  fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  text: (q: string, mode: Exclude<Mode, 'temporal'>, k: number, group: boolean) =>
    j<Results>(post('/search/text', { q, mode, k, group_by_video: group })),
  temporal: (qa: string, qb: string, maxShots: number, maxSeconds: number | null, k: number, group: boolean) =>
    j<Results>(post('/search/temporal', { qa, qb, max_shots: maxShots, max_seconds: maxSeconds, k, group_by_video: group })),
  image: (blob: Blob, k: number, group: boolean) => {
    const fd = new FormData()
    fd.append('file', blob, 'query.png')
    fd.append('k', String(k))
    fd.append('group_by_video', String(group))
    return j<Results>(fetch('/search/image', { method: 'POST', body: fd }))
  },
  similar: (shotId: string, k: number, group: boolean) =>
    j<Results>(fetch(`/search/similar/${shotId}?k=${k}&group_by_video=${group}`)),
  feedback: (positives: string[], negatives: string[], q: string | null, k: number, group: boolean) =>
    j<Results>(post('/search/feedback', { positives, negatives, q, k, group_by_video: group })),
  videoShots: (v3c: string) => j<VideoInfo>(fetch(`/video/${v3c}/shots`)),
  dresStatus: () => j<DresStatus>(fetch('/dres/status')),
  dresLogin: () => j<unknown>(post('/dres/login', {})),
  dresSubmit: (answers: Answer[]) => j<{ results: SubmitResult[] }>(post('/dres/submit', { answers })),
  dresLog: () => j<SubmitResult[]>(fetch('/dres/log?limit=100')),
}

export const thumbUrl = (shotId: string) => `/thumb/${shotId}`
export const videoUrl = (v3c: string) => `/video/${v3c}.mp4`
export const fmtMs = (ms: number) => {
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}.${String(ms % 1000).padStart(3, '0')}`
}
