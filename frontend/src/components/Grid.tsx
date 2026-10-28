import { useEffect, useRef } from 'react'
import { type Shot, type TaskType, thumbUrl } from '../api'

type Props = {
  results: Shot[]
  cursor: number
  taskType: TaskType
  queued: Set<string>
  submitted: Set<string>
  positives: Set<string>
  negatives: Set<string>
  onCursor: (i: number) => void
  onOpen: (s: Shot) => void
  onSimilar: (s: Shot) => void
  onToggleQueue: (s: Shot) => void
  gridRef: React.RefObject<HTMLDivElement | null>
}

export function Grid(p: Props) {
  const cardRefs = useRef<(HTMLDivElement | null)[]>([])

  useEffect(() => {
    cardRefs.current[p.cursor]?.scrollIntoView({ block: 'nearest' })
  }, [p.cursor])

  if (!p.results.length) return <div className="empty">No results. Type a query and press Enter, or paste a screenshot (⌘V).</div>

  return (
    <div className="grid" ref={p.gridRef}>
      {p.results.map((s, i) => {
        const cls = ['card']
        if (i === p.cursor) cls.push('cursor')
        if (p.queued.has(s.shot_id)) cls.push('queued')
        if (p.submitted.has(s.shot_id)) cls.push('submitted')
        if (p.positives.has(s.shot_id)) cls.push('pos')
        if (p.negatives.has(s.shot_id)) cls.push('neg')
        return (
          <div key={s.shot_id + i} className={cls.join(' ')} ref={(el) => { cardRefs.current[i] = el }}
               onClick={() => p.onCursor(i)} onDoubleClick={() => p.onOpen(s)}>
            <img src={thumbUrl(s.shot_id)} loading="lazy" decoding="async" alt="" />
            {s.next_shot && <img className="inset" src={thumbUrl(s.next_shot.shot_id)} loading="lazy" alt="" />}
            <div className="cap">
              <span>{s.v3c_id} #{s.n}</span>
              <span className="btns">
                {p.taskType === 'AVS' && (
                  <button title="Add to AVS queue (A)" onClick={(e) => { e.stopPropagation(); p.onToggleQueue(s) }}>
                    {p.queued.has(s.shot_id) ? '✓' : '+'}
                  </button>
                )}
                <button title="More like this (M)" onClick={(e) => { e.stopPropagation(); p.onSimilar(s) }}>≈</button>
                <button title="Open in player (Space)" onClick={(e) => { e.stopPropagation(); p.onOpen(s) }}>▶</button>
              </span>
            </div>
            <div className="tip">
              <b>{s.title}</b>
              <div>{s.v3c_id} shot {s.n} · {(s.start_ms / 1000).toFixed(1)}–{(s.end_ms / 1000).toFixed(1)}s · {s.score.toFixed(3)}</div>
              {s.snippet && <div className="snip">“{s.snippet}”</div>}
              {s.next_shot && <div>→ then shot {s.next_shot.n}</div>}
            </div>
          </div>
        )
      })}
    </div>
  )
}
