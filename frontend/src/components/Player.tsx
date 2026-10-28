import { useEffect, useRef, useState } from 'react'
import { type Shot, type VideoInfo, fmtMs, thumbUrl, videoUrl } from '../api'

export type Range = { start: number; end: number }

type Props = {
  shot: Shot | null
  info: VideoInfo | null
  range: Range
  setRange: (r: Range) => void
  loop: boolean
  setLoop: (b: boolean) => void
  onPickShot: (s: Shot) => void
  onSubmit: () => void
  submitLabel: string
  submitDisabled: boolean
  videoRef: React.RefObject<HTMLVideoElement | null>
}

const STRIP = 10 // neighbouring shots shown on each side

export function Player(p: Props) {
  const [now, setNow] = useState(0)
  const pendingSeek = useRef<number | null>(null)
  const src = p.shot ? videoUrl(p.shot.v3c_id) : ''

  // seek to the range start whenever the shot (or its range) changes
  useEffect(() => {
    const v = p.videoRef.current
    if (!v || !p.shot) return
    const t = p.range.start / 1000
    if (v.readyState >= 1 && v.currentSrc.endsWith(src)) {
      v.currentTime = t
      v.play().catch(() => {})
    } else {
      pendingSeek.current = t
    }
  }, [p.shot?.shot_id, src])

  // ms clock + loop of [start, end]
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const v = p.videoRef.current
      if (v) {
        const ms = Math.round(v.currentTime * 1000)
        setNow(ms)
        if (p.loop && !v.paused && ms >= p.range.end) {
          v.currentTime = p.range.start / 1000
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [p.loop, p.range.start, p.range.end, p.videoRef])

  if (!p.shot) return <div className="player empty">Select a result and press Space to play it here.</div>

  const shots = p.info?.v3c_id === p.shot.v3c_id ? p.info.shots : []
  const idx = shots.findIndex((s) => s.shot_id === p.shot!.shot_id)
  const strip = idx >= 0 ? shots.slice(Math.max(0, idx - STRIP), idx + STRIP + 1) : []
  const playing = shots.find((s) => now >= s.start_ms && now < s.end_ms)

  return (
    <div className="player">
      <div className="ptitle">
        <b>{p.shot.v3c_id}</b> {p.info?.title ?? p.shot.title}
      </div>
      <video ref={p.videoRef} src={src} controls autoPlay playsInline preload="auto"
             onLoadedMetadata={(e) => {
               if (pendingSeek.current !== null) {
                 e.currentTarget.currentTime = pendingSeek.current
                 pendingSeek.current = null
               }
               e.currentTarget.play().catch(() => {})
             }} />
      <div className="strip">
        {strip.map((s) => (
          <img key={s.shot_id} src={thumbUrl(s.shot_id)} title={`shot ${s.n} · ${fmtMs(s.start_ms)}`}
               className={(s.shot_id === p.shot!.shot_id ? 'cur ' : '') + (s === playing ? 'playing' : '')}
               onClick={() => p.onPickShot(s)} />
        ))}
      </div>
      <div className="times">
        <span className="now" title="current playback time">{now} ms <small>({fmtMs(now)})</small></span>
        <span>shot {playing?.n ?? '–'}</span>
        <label><input type="checkbox" checked={p.loop} onChange={(e) => p.setLoop(e.target.checked)} /> loop (L)</label>
      </div>
      <div className="range">
        <label>start
          <input type="number" value={p.range.start} step={40}
                 onChange={(e) => p.setRange({ ...p.range, start: Number(e.target.value) })} />
        </label>
        <button title="Set start to current time ([)" onClick={() => p.setRange({ ...p.range, start: now })}>[ now</button>
        <label>end
          <input type="number" value={p.range.end} step={40}
                 onChange={(e) => p.setRange({ ...p.range, end: Number(e.target.value) })} />
        </label>
        <button title="Set end to current time (])" onClick={() => p.setRange({ ...p.range, end: now })}>now ]</button>
        <button title="Reset range to the shot boundaries (R)"
                onClick={() => p.setRange({ start: p.shot!.start_ms, end: p.shot!.end_ms })}>reset</button>
      </div>
      <button className="submit" disabled={p.submitDisabled} onClick={p.onSubmit}>{p.submitLabel}</button>
    </div>
  )
}
