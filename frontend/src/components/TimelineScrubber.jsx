import { useEffect, useRef } from 'react'

export default function TimelineScrubber({ frames, frameIdx, setFrameIdx, isPlaying, setIsPlaying, peakDensity, peakPressure, hotspots }) {
  const intervalRef = useRef(null)

  useEffect(() => {
    if (isPlaying && frames.length > 0) {
      intervalRef.current = setInterval(() => {
        setFrameIdx(i => {
          if (i >= frames.length - 1) { setIsPlaying(false); return i }
          return i + 1
        })
      }, 100)
    }
    return () => clearInterval(intervalRef.current)
  }, [isPlaying, frames.length, setFrameIdx, setIsPlaying])

  const currentT = frames[frameIdx]?.t ?? 0

  return (
    <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Stats row */}
      <div style={{ display: 'flex', gap: 12 }}>
        <StatCard label="Peak Density" value={`${peakDensity.toFixed(1)} p/m²`} level={densityLevel(peakDensity)} />
        <StatCard label="Peak Pressure" value={peakPressure.toFixed(2)} level={pressureLevel(peakPressure)} />
        <StatCard label="Hotspots" value={hotspots.length} level={hotspots.length > 3 ? 'red' : hotspots.length > 0 ? 'orange' : 'green'} />
        <StatCard label="Frame" value={`${frameIdx + 1} / ${frames.length}`} level="neutral" />
        <StatCard label="Sim Time" value={`${currentT.toFixed(1)}s`} level="neutral" />
      </div>

      {/* Playback */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button
          onClick={() => setFrameIdx(0)}
          style={btnStyle}
          title="Reset"
        >⏮</button>

        <button
          onClick={() => setIsPlaying(p => !p)}
          disabled={frames.length === 0}
          style={{ ...btnStyle, background: '#3b82f6', color: '#fff', padding: '6px 16px', opacity: frames.length === 0 ? 0.4 : 1 }}
        >
          {isPlaying ? '⏸ Pause' : '▶ Play'}
        </button>

        <button
          onClick={() => setFrameIdx(frames.length - 1)}
          style={btnStyle}
          title="End"
        >⏭</button>

        <input
          type="range"
          min={0}
          max={Math.max(0, frames.length - 1)}
          value={frameIdx}
          onChange={e => { setIsPlaying(false); setFrameIdx(Number(e.target.value)) }}
          style={{ flex: 1, accentColor: '#3b82f6', height: 4, background: 'transparent' }}
        />
      </div>

      {/* Hotspot list */}
      {hotspots.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {hotspots.slice(0, 5).map((h, i) => (
            <div key={i} style={{
              background: 'rgba(239,68,68,0.12)',
              border: '1px solid rgba(239,68,68,0.3)',
              borderRadius: 6,
              padding: '3px 8px',
              fontSize: 11,
              color: '#fca5a5',
            }}>
              ◎ Hotspot {i + 1} — {h.peak_density.toFixed(1)} p/m²
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const btnStyle = {
  background: '#27272a',
  color: '#a1a1aa',
  border: '1px solid #3f3f46',
  borderRadius: 6,
  padding: '6px 10px',
  fontSize: 13,
}

function StatCard({ label, value, level }) {
  const colors = {
    green:   ['#14532d', '#22c55e'],
    yellow:  ['#713f12', '#eab308'],
    orange:  ['#7c2d12', '#f97316'],
    red:     ['#7f1d1d', '#ef4444'],
    neutral: ['#27272a', '#a1a1aa'],
  }
  const [bg, fg] = colors[level] ?? colors.neutral
  return (
    <div style={{
      background: bg, borderRadius: 8, padding: '8px 14px', flex: 1,
      border: `1px solid ${fg}33`,
    }}>
      <div style={{ color: fg, fontWeight: 700, fontSize: 16 }}>{value}</div>
      <div style={{ color: '#71717a', fontSize: 11, marginTop: 2 }}>{label}</div>
    </div>
  )
}

function densityLevel(d) {
  if (d >= 6) return 'red'
  if (d >= 4) return 'orange'
  if (d >= 3) return 'yellow'
  if (d > 0)  return 'green'
  return 'neutral'
}

function pressureLevel(p) {
  if (p >= 5) return 'red'
  if (p >= 3) return 'orange'
  if (p >= 1) return 'yellow'
  return 'neutral'
}
