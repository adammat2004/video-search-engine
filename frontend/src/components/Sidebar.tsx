import { type Shot, type SubmitResult, type TaskType, fmtMs, thumbUrl } from '../api'

export const MAX_PER_VIDEO = 3

type TaskProps = {
  taskType: TaskType
  kisDone: boolean
  queue: Shot[]
  taskSubs: SubmitResult[]
  onRemove: (s: Shot) => void
  onSubmitQueue: () => void
  onNewTask: () => void
}

export function perVideoCounts(queue: Shot[], subs: SubmitResult[]) {
  const c = new Map<string, number>()
  for (const v of [...queue.map((s) => s.v3c_id), ...subs.map((s) => s.v3c_id)]) c.set(v, (c.get(v) ?? 0) + 1)
  return c
}

export function TaskPanel(p: TaskProps) {
  const counts = perVideoCounts(p.queue, p.taskSubs)
  const crowded = [...counts].filter(([, n]) => n > MAX_PER_VIDEO).map(([v]) => v)
  const correct = p.taskSubs.filter((s) => s.verdict === 'CORRECT').length
  return (
    <div className="task">
      <div className="task-head">
        <b>{p.taskType} task</b>
        <span>{p.taskSubs.length} submitted · {correct} correct</span>
        <button onClick={p.onNewTask} title="Clear queue and per-task state (Shift+N)">new task (⇧N)</button>
      </div>
      {p.taskType === 'KIS' && p.kisDone && <div className="banner ok">Task solved. Press Shift+N for the next task.</div>}
      {p.taskType === 'AVS' && (
        <>
          {crowded.length > 0 && (
            <div className="banner warn">More than {MAX_PER_VIDEO} segments from video {crowded.join(', ')}. Diverse videos score better.</div>
          )}
          <div className="queue">
            {p.queue.map((s) => (
              <div key={s.shot_id} className={'qitem' + ((counts.get(s.v3c_id) ?? 0) > MAX_PER_VIDEO ? ' crowded' : '')}
                   title={`${s.title}\n${fmtMs(s.start_ms)}–${fmtMs(s.end_ms)}`} onClick={() => p.onRemove(s)}>
                <img src={thumbUrl(s.shot_id)} alt="" />
                <span>{s.v3c_id}#{s.n}</span>
              </div>
            ))}
            {!p.queue.length && <span className="muted">Queue empty. Press A on results to add.</span>}
          </div>
          <button className="submit" disabled={!p.queue.length} onClick={p.onSubmitQueue}>
            Submit {p.queue.length} segment{p.queue.length === 1 ? '' : 's'} (S)
          </button>
        </>
      )}
    </div>
  )
}

const VERDICT_CLASS: Record<string, string> = { CORRECT: 'ok', WRONG: 'bad', ERROR: 'bad' }

export function SubmissionLog({ log }: { log: SubmitResult[] }) {
  return (
    <div className="log">
      <div className="log-head">Submission log</div>
      {log.map((s, i) => (
        <div key={i} className={'logrow ' + (VERDICT_CLASS[s.verdict ?? ''] ?? 'pending')}
             title={s.description}>
          <span className="v">{s.verdict ?? '?'}</span>
          <span>{s.v3c_id}</span>
          <span>{s.start_ms}–{s.end_ms}</span>
          <span className="muted">{s.time?.slice(11) ?? ''}</span>
        </div>
      ))}
      {!log.length && <div className="muted">Nothing submitted yet.</div>}
    </div>
  )
}
