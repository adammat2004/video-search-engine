import { useCallback, useEffect, useRef, useState } from 'react'
import {
  type Answer, type DresStatus, type Mode, type Shot, type SubmitResult, type TaskType, type VideoInfo,
  api, fmtMs,
} from './api'
import { Grid } from './components/Grid'
import { Player, type Range } from './components/Player'
import { MAX_PER_VIDEO, SubmissionLog, TaskPanel, perVideoCounts } from './components/Sidebar'

const K = 300
const MODES: { id: Mode; label: string }[] = [
  { id: 'visual', label: 'Visual' },
  { id: 'speech', label: 'Speech' },
  { id: 'fused', label: 'Fused' },
  { id: 'temporal', label: 'A→B' },
]
type Results = { results: Shot[] }
type Confirm = { answers: Answer[]; lines: string[]; warn?: string }

export default function App() {
  // search
  const [mode, setMode] = useState<Mode>('fused')
  const [q, setQ] = useState('')
  const [qb, setQb] = useState('')
  const [maxShots, setMaxShots] = useState(5)
  const [maxSeconds, setMaxSeconds] = useState('')
  const [group, setGroup] = useState(false)
  const [results, setResults] = useState<Shot[]>([])
  const [cursor, setCursor] = useState(0)
  const [status, setStatus] = useState<{ text: string; err?: boolean }>({ text: 'Ready' })
  const [pasted, setPasted] = useState<string | null>(null)
  const [positives, setPositives] = useState<Set<string>>(new Set())
  const [negatives, setNegatives] = useState<Set<string>>(new Set())
  const lastSearch = useRef<((group: boolean) => Promise<Results>) | null>(null)

  // player
  const [shot, setShot] = useState<Shot | null>(null)
  const [info, setInfo] = useState<VideoInfo | null>(null)
  const [range, setRange] = useState<Range>({ start: 0, end: 0 })
  const [loop, setLoop] = useState(true)
  const videoRef = useRef<HTMLVideoElement | null>(null)

  // task + DRES
  const [taskType, setTaskType] = useState<TaskType>('KIS')
  const [queue, setQueue] = useState<Shot[]>([])
  const [taskSubs, setTaskSubs] = useState<SubmitResult[]>([])
  const [kisDone, setKisDone] = useState(false)
  const [log, setLog] = useState<SubmitResult[]>([])
  const [dres, setDres] = useState<DresStatus | null>(null)
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const queryRef = useRef<HTMLInputElement | null>(null)
  const gridRef = useRef<HTMLDivElement | null>(null)

  // ------------------------------------------------------------------ searching
  const run = useCallback(async (label: string, fn: (group: boolean) => Promise<Results>, g = group) => {
    lastSearch.current = fn
    setStatus({ text: `${label}…` })
    const t = performance.now()
    try {
      const r = await fn(g)
      setResults(r.results)
      setCursor(0)
      setStatus({ text: `${label}: ${r.results.length} results in ${Math.round(performance.now() - t)} ms` })
    } catch (e) {
      setStatus({ text: `${label} failed: ${(e as Error).message}`, err: true })
    }
  }, [group])

  // "00031", "00031 1", "00031#1" or "shot00031_1": jump straight to a video (and shot) by id
  const jumpTo = async (v3c: string, n: number | null) => {
    try {
      const v = await api.videoShots(v3c)
      lastSearch.current = null
      setResults(v.shots)
      setInfo(v)
      const i = n ? v.shots.findIndex((s) => s.n === n) : -1
      setCursor(Math.max(0, i))
      if (i >= 0) open(v.shots[i])
      setStatus({ text: `video ${v3c} (${v.title}): ${v.shots.length} shots` + (n && i < 0 ? ` (no shot ${n})` : '') })
    } catch (e) {
      setStatus({ text: `video ${v3c}: ${(e as Error).message}`, err: true })
    }
  }

  const search = () => {
    if (!q.trim()) return
    const id = q.trim().match(/^(?:shot)?(\d{5})(?:[\s_#]+(\d+))?$/i)
    if (id && mode !== 'temporal') { jumpTo(id[1], id[2] ? Number(id[2]) : null); return }
    if (mode === 'temporal') {
      if (!qb.trim()) { setStatus({ text: 'Temporal search needs both A and B', err: true }); return }
      const secs = maxSeconds ? Number(maxSeconds) : null
      run(`A→B "${q}" → "${qb}"`, (g) => api.temporal(q, qb, maxShots, secs, K, g))
    } else {
      run(`${mode} "${q}"`, (g) => api.text(q, mode, K, g))
    }
  }

  const imageSearch = (blob: Blob) => {
    setPasted((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(blob) })
    run('image', (g) => api.image(blob, K, g))
  }

  const similar = (s: Shot) => run(`like ${s.shot_id}`, (g) => api.similar(s.shot_id, K, g))

  const feedbackSearch = () => {
    if (!positives.size) { setStatus({ text: 'Mark positives with P (negatives with X) first', err: true }); return }
    const text = mode === 'visual' || mode === 'fused' ? q.trim() || null : null
    run(`feedback +${positives.size}/−${negatives.size}`,
      (g) => api.feedback([...positives], [...negatives], text, K, g))
  }

  const toggleGroup = () => {
    const g = !group
    setGroup(g)
    if (lastSearch.current) run('regroup', lastSearch.current, g)
  }

  // ------------------------------------------------------------------ player
  const open = (s: Shot) => {
    setShot(s)
    setRange({ start: s.start_ms, end: s.end_ms })
    if (info?.v3c_id !== s.v3c_id) {
      api.videoShots(s.v3c_id).then(setInfo).catch((e) => setStatus({ text: e.message, err: true }))
    }
  }

  const nowMs = () => Math.round((videoRef.current?.currentTime ?? 0) * 1000)

  // ------------------------------------------------------------------ task + submission
  const submittedIds = new Set(taskSubs.map((s) => s.shot_id).filter(Boolean) as string[])
  const queued = new Set(queue.map((s) => s.shot_id))

  const toggleQueue = (s: Shot) => {
    if (submittedIds.has(s.shot_id)) { setStatus({ text: `${s.shot_id} already submitted in this task`, err: true }); return }
    setQueue((qq) => qq.some((x) => x.shot_id === s.shot_id) ? qq.filter((x) => x.shot_id !== s.shot_id) : [...qq, s])
  }

  const askSubmit = () => {
    if (taskType === 'KIS') {
      if (!shot) { setStatus({ text: 'Open a shot in the player first', err: true }); return }
      if (kisDone) { setStatus({ text: 'Task already solved. Press Shift+N for a new task.', err: true }); return }
      if (range.end <= range.start) { setStatus({ text: 'End must be after start', err: true }); return }
      if (taskSubs.some((s) => s.v3c_id === shot.v3c_id && s.start_ms === range.start && s.end_ms === range.end)) {
        setStatus({ text: 'This exact segment was already submitted', err: true }); return
      }
      setConfirm({
        answers: [{ shot_id: shot.shot_id, v3c_id: shot.v3c_id, start_ms: range.start, end_ms: range.end }],
        lines: [`${shot.v3c_id}  ${range.start}–${range.end} ms  (${fmtMs(range.start)}–${fmtMs(range.end)}, shot ${shot.n})`],
        warn: taskSubs.some((s) => s.verdict === 'WRONG') ? 'Previous submission was WRONG. Another wrong one costs points.' : undefined,
      })
    } else {
      const todo = queue.filter((s) => !submittedIds.has(s.shot_id))
      if (!todo.length) { setStatus({ text: 'AVS queue is empty', err: true }); return }
      const crowded = [...perVideoCounts(todo, taskSubs)].filter(([, n]) => n > MAX_PER_VIDEO).map(([v]) => v)
      setConfirm({
        answers: todo.map((s) => ({ shot_id: s.shot_id })),
        lines: todo.map((s) => `${s.v3c_id} #${s.n}  ${s.start_ms}–${s.end_ms} ms`),
        warn: crowded.length ? `More than ${MAX_PER_VIDEO} segments from ${crowded.join(', ')}` : undefined,
      })
    }
  }

  const refreshLog = () => api.dresLog().then(setLog).catch(() => {})

  const doSubmit = async () => {
    if (!confirm || submitting) return
    const answers = confirm.answers
    setConfirm(null)
    setSubmitting(true)
    setStatus({ text: `Submitting ${answers.length}…` })
    try {
      const { results: res } = await api.dresSubmit(answers)
      setTaskSubs((t) => [...t, ...res])
      const verdicts = res.map((r) => r.verdict ?? '?')
      setStatus({ text: `DRES: ${verdicts.join(', ')}`, err: verdicts.some((v) => v === 'WRONG' || v === 'ERROR') })
      if (taskType === 'KIS' && res.some((r) => r.verdict === 'CORRECT')) setKisDone(true)
      if (taskType === 'AVS') {
        const done = new Set(res.map((r) => r.shot_id))
        setQueue((qq) => qq.filter((s) => !done.has(s.shot_id)))
      }
    } catch (e) {
      setStatus({ text: `Submit failed: ${(e as Error).message}`, err: true })
    } finally {
      setSubmitting(false)
      refreshLog()
    }
  }

  const newTask = () => {
    setQueue([]); setTaskSubs([]); setKisDone(false)
    setPositives(new Set()); setNegatives(new Set())
    setResults([]); setQ(''); setQb(''); setPasted(null); lastSearch.current = null
    setStatus({ text: 'New task' })
    queryRef.current?.focus()
  }

  // ------------------------------------------------------------------ DRES status polling
  useEffect(() => {
    const poll = () => api.dresStatus().then(setDres).catch(() => setDres(null))
    poll(); refreshLog()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [])

  const dresLogin = () =>
    api.dresLogin().then(() => api.dresStatus().then(setDres))
      .catch((e) => setStatus({ text: `DRES login failed: ${e.message}`, err: true }))

  // ------------------------------------------------------------------ keyboard + paste
  const cols = () => {
    const el = gridRef.current
    return el ? getComputedStyle(el).gridTemplateColumns.split(' ').length : 1
  }
  const toggleIn = (set: Set<string>, setter: (s: Set<string>) => void, id: string, other: Set<string>, otherSetter: (s: Set<string>) => void) => {
    const n = new Set(set); if (n.has(id)) n.delete(id); else n.add(id); setter(n)
    if (other.has(id)) { const o = new Set(other); o.delete(id); otherSetter(o) }
  }

  const onKey = (e: KeyboardEvent) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (confirm) {
      if (e.key === 'y' || e.key === 'Y' || e.key === 'Enter') { e.preventDefault(); doSubmit() }
      if (e.key === 'Escape' || e.key === 'n') { e.preventDefault(); setConfirm(null) }
      return
    }
    const t = e.target as HTMLElement
    if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') {
      if (e.key === 'Escape') t.blur()
      return
    }
    if ((t.tagName === 'BUTTON' || t.tagName === 'VIDEO') && (e.key === ' ' || e.key === 'Enter')) return
    const cur = results[cursor]
    const move = (d: number) => { e.preventDefault(); setCursor((c) => Math.max(0, Math.min(results.length - 1, c + d))) }
    switch (e.key) {
      case '/': e.preventDefault(); queryRef.current?.focus(); queryRef.current?.select(); break
      case '1': case '2': case '3': case '4': setMode(MODES[Number(e.key) - 1].id); break
      case 'ArrowRight': move(1); break
      case 'ArrowLeft': move(-1); break
      case 'ArrowDown': move(cols()); break
      case 'ArrowUp': move(-cols()); break
      case ' ': case 'Enter': e.preventDefault(); if (cur) open(cur); break
      case 'm': if (cur) similar(cur); break
      case 'a': if (cur && taskType === 'AVS') toggleQueue(cur); break
      case 's': askSubmit(); break
      case 'g': toggleGroup(); break
      case 'N': newTask(); break
      case 't': setTaskType((tt) => (tt === 'KIS' ? 'AVS' : 'KIS')); break
      case 'l': setLoop((l) => !l); break
      case '[': setRange((r) => ({ ...r, start: nowMs() })); break
      case ']': setRange((r) => ({ ...r, end: nowMs() })); break
      case 'r': if (shot) setRange({ start: shot.start_ms, end: shot.end_ms }); break
      case 'k': { const v = videoRef.current; if (v) { if (v.paused) v.play(); else v.pause() } break }
      case 'p': if (cur) toggleIn(positives, setPositives, cur.shot_id, negatives, setNegatives); break
      case 'x': if (cur) toggleIn(negatives, setNegatives, cur.shot_id, positives, setPositives); break
      case 'f': feedbackSearch(); break
    }
  }
  const keyRef = useRef(onKey)
  keyRef.current = onKey
  const pasteRef = useRef(imageSearch)
  pasteRef.current = imageSearch

  useEffect(() => {
    const kd = (e: KeyboardEvent) => keyRef.current(e)
    const paste = (e: ClipboardEvent) => {
      const item = [...(e.clipboardData?.items ?? [])].find((i) => i.type.startsWith('image/'))
      const file = item?.getAsFile()
      if (file) { e.preventDefault(); pasteRef.current(file) }
    }
    window.addEventListener('keydown', kd)
    window.addEventListener('paste', paste)
    return () => { window.removeEventListener('keydown', kd); window.removeEventListener('paste', paste) }
  }, [])

  // ------------------------------------------------------------------ render
  const dresClass = !dres?.configured ? 'off' : !dres.logged_in || dres.error ? 'bad' : dres.active?.length ? 'ok' : 'warn'
  const dresText = !dres ? 'backend down' : !dres.configured ? 'DRES not configured'
    : !dres.logged_in ? 'DRES: click to log in' : dres.error ? `DRES error`
    : dres.active?.length ? `${dres.active[0].name}${dres.current_task ? ' · ' + dres.current_task.name : ''}` : 'DRES: no active evaluation'

  return (
    <div className="app">
      <header className="top">
        <div className="modes">
          {MODES.map((m, i) => (
            <button key={m.id} className={mode === m.id ? 'on' : ''} onClick={() => setMode(m.id)} title={`Key ${i + 1}`}>{m.label}</button>
          ))}
        </div>
        <form className="qform" onSubmit={(e) => { e.preventDefault(); search() }}>
          <input ref={queryRef} value={q} onChange={(e) => setQ(e.target.value)} autoFocus
                 placeholder={mode === 'temporal' ? 'A: first shot…' : mode === 'speech' ? 'spoken words, title, tags…' : 'describe the shot, or a video id like 00031 1  (/ to focus)'} />
          {mode === 'temporal' && (
            <>
              <input value={qb} onChange={(e) => setQb(e.target.value)} placeholder="B: followed by…" />
              <label className="small">≤<input type="number" min={1} max={50} value={maxShots} onChange={(e) => setMaxShots(Number(e.target.value))} /> shots</label>
              <label className="small">≤<input type="number" min={0} placeholder="∞" value={maxSeconds} onChange={(e) => setMaxSeconds(e.target.value)} /> s</label>
            </>
          )}
          <button type="submit">Search</button>
        </form>
        <div className="paste" title="Paste (⌘V) or drop a screenshot to search by image"
             onDragOver={(e) => e.preventDefault()}
             onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f?.type.startsWith('image/')) imageSearch(f) }}>
          {pasted ? <img src={pasted} alt="" /> : <span>⌘V image</span>}
        </div>
        <button className={group ? 'on' : ''} onClick={toggleGroup} title="Best shot per video (G)">by video</button>
        <div className="tasktype" title="Task type (T)">
          {(['KIS', 'AVS'] as TaskType[]).map((t) => (
            <button key={t} className={taskType === t ? 'on' : ''} onClick={() => setTaskType(t)}>{t}</button>
          ))}
        </div>
        <div className={`dres ${dresClass}`} onClick={dres?.configured && !dres.logged_in ? dresLogin : undefined}
             title={dres?.error ?? dres?.url}>
          <span className="dot" />{dresText}
        </div>
      </header>
      <div className={'status' + (status.err ? ' err' : '')}>
        {status.text}
        <span className="keys">/ query · 1–4 mode · ←↑→↓ move · Space play · M similar · S submit · A queue · G group · T task · ⇧N new task · [ ] range · P/X/F feedback</span>
      </div>
      <main>
        <section className="results">
          <Grid results={results} cursor={cursor} taskType={taskType} queued={queued} submitted={submittedIds}
                positives={positives} negatives={negatives} onCursor={setCursor} onOpen={open}
                onSimilar={similar} onToggleQueue={toggleQueue} gridRef={gridRef} />
        </section>
        <aside className="side">
          <Player shot={shot} info={info} range={range} setRange={setRange} loop={loop} setLoop={setLoop}
                  onPickShot={open} videoRef={videoRef} onSubmit={askSubmit}
                  submitDisabled={taskType !== 'KIS' || kisDone || submitting}
                  submitLabel={taskType === 'KIS' ? (kisDone ? 'Solved ✓' : 'Submit segment (S)') : 'AVS: queue shots with A'} />
          <TaskPanel taskType={taskType} kisDone={kisDone} queue={queue} taskSubs={taskSubs}
                     onRemove={toggleQueue} onSubmitQueue={askSubmit} onNewTask={newTask} />
          <SubmissionLog log={log} />
        </aside>
      </main>
      {confirm && (
        <div className="modal" onClick={() => setConfirm(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>Submit {confirm.answers.length} {taskType} answer{confirm.answers.length > 1 ? 's' : ''} to DRES?</h3>
            <pre>{confirm.lines.join('\n')}</pre>
            {confirm.warn && <div className="banner warn">{confirm.warn}</div>}
            <div className="actions">
              <button className="submit" onClick={doSubmit}>Submit (Y / Enter)</button>
              <button onClick={() => setConfirm(null)}>Cancel (Esc)</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
