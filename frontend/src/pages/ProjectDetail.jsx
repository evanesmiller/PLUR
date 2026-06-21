import { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import DeckMap from '../deck/DeckMap.jsx'
import { api } from '../api/client.js'

const STAGE_COLORS = {
  hard: '#ef4444', harder: '#f97316', green: '#22c55e',
  purple: '#a855f7', pink: '#ec4899', beatbox: '#22d3ee', locals_only: '#fbbf24',
}

const PANEL_W = 272

function generateSlots(startTime, endTime) {
  const parse = t => { const [h, m] = t.split(':').map(Number); return h * 60 + (m || 0) }
  let start = parse(startTime || '12:00')
  let end = parse(endTime || '00:00')
  if (end <= start) end += 24 * 60
  const slots = []
  for (let t = start; t < end; t += 60) {
    const h1 = Math.floor(t / 60) % 24
    const h2 = Math.floor((t + 60) / 60) % 24
    slots.push({
      label: `${String(h1).padStart(2, '0')}:00 – ${String(h2).padStart(2, '0')}:00`,
      start: `${String(h1).padStart(2, '0')}:00`,
      end: `${String(h2).padStart(2, '0')}:00`,
    })
  }
  return slots
}

function setlistToSchedule(setlist, stages, slots) {
  const schedule = {}
  for (const stage of stages) {
    schedule[stage.id] = {}
    for (let i = 0; i < slots.length; i++) schedule[stage.id][i] = { artist: null, locked: false }
  }
  for (const item of setlist ?? []) {
    const idx = slots.findIndex(s => s.start === item.start)
    if (idx !== -1 && schedule[item.stage]) {
      schedule[item.stage][idx] = { artist: item.artist, locked: item.locked ?? false }
    }
  }
  return schedule
}

function scheduleToSetlist(schedule, stages, slots) {
  const result = []
  for (const stage of stages) {
    for (let i = 0; i < slots.length; i++) {
      const cell = schedule[stage.id]?.[i]
      if (cell?.artist) {
        result.push({ artist: cell.artist, stage: stage.id, start: slots[i].start, end: slots[i].end, locked: cell.locked })
      }
    }
  }
  return result
}

export default function ProjectDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [setlist, setSetlist] = useState([])
  const [vis, setVis] = useState({
    heatmap: true, agents: false, zones: true,
    barriers: true, staff: true, hotspots: true,
  })
  const [simParams, setSimParams] = useState({
    capacity: 80000, tickets_sold: 60000,
    density_orange: 4, density_red: 6,
  })
  const [simRunning, setSimRunning] = useState(false)
  const [simResult, setSimResult] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [timelinePct, setTimelinePct] = useState(0)
  const [beforeAfterLayout, setBeforeAfterLayout] = useState('before')
  const [beforeAfterSchedule, setBeforeAfterSchedule] = useState('before')
  const [showSetTimes, setShowSetTimes] = useState(false)
  const [addMode, setAddMode] = useState(null)

  useEffect(() => {
    api.getProject(id)
      .then(p => {
        setProject(p)
        setSetlist(p.setlist ?? [])
        setSimParams(prev => ({
          ...prev,
          capacity: p.meta?.max_occupancy ?? 80000,
          tickets_sold: p.meta?.expected_attendance ?? Math.round((p.meta?.max_occupancy ?? 80000) * 0.8),
        }))
      })
      .catch(() => navigate('/'))
      .finally(() => setLoading(false))
  }, [id])

  const stages = useMemo(() => {
    if (!project?.geojson) return []
    return (project.geojson.features ?? [])
      .filter(f => f.properties?.type === 'stage')
      .map(f => ({
        id: f.properties.stage_id ?? f.properties.id ?? f.properties.name?.toLowerCase().replace(/\s+/g, '_') ?? 'unknown',
        name: f.properties.name ?? f.properties.stage_id ?? 'Stage',
        color: STAGE_COLORS[f.properties.stage_id] ?? '#888',
      }))
  }, [project])

  const slots = useMemo(() => {
    if (!project?.meta) return []
    return generateSlots(project.meta.start_time ?? '12:00', project.meta.end_time ?? '00:00')
  }, [project])

  async function handleRunSim() {
    setSimRunning(true)
    try {
      const result = await api.simulate(
        setlist.length > 0 ? setlist : null,
        null,
        {
          max_capacity: simParams.capacity,
          tickets_sold: simParams.tickets_sold,
          n_agents: 1000,
        },
        { t_start: 0, t_end: 10 },
      )
      setSimResult(result)
      setTimelinePct(0)
    } catch (err) {
      console.error('Simulation failed:', err)
      alert('Simulation failed: ' + err.message)
    } finally {
      setSimRunning(false)
    }
  }

  async function handleSaveQuit() {
    try { await api.updateProject(id, { setlist }) } catch {}
    navigate('/')
  }

  async function handleSetTimesSave(newSetlist) {
    setSetlist(newSetlist)
    try { await api.updateProject(id, { setlist: newSetlist }) } catch {}
    setShowSetTimes(false)
  }

  useEffect(() => {
    if (!playing || !simResult?.frames?.length) return
    const interval = setInterval(() => {
      setTimelinePct(p => {
        const next = p + (speed * 0.02)
        if (next >= 1) { setPlaying(false); return 1 }
        return next
      })
    }, 50)
    return () => clearInterval(interval)
  }, [playing, speed, simResult])

  const currentFrame = useMemo(() => {
    if (!simResult?.frames?.length) return []
    const idx = Math.min(
      Math.floor(timelinePct * simResult.frames.length),
      simResult.frames.length - 1,
    )
    return simResult.frames[idx]?.agents ?? []
  }, [simResult, timelinePct])

  if (loading) {
    return (
      <div style={{
        width: '100vw', height: '100vh', background: '#09090b',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#52525b', fontFamily: 'Inter, system-ui, sans-serif', fontSize: 14,
      }}>
        Loading project…
      </div>
    )
  }

  if (!project) return null

  return (
    <div style={{
      width: '100vw', height: '100vh', background: '#09090b',
      position: 'relative', overflow: 'hidden',
      fontFamily: 'Inter, system-ui, sans-serif', color: '#f4f4f5',
    }}>
      <DeckMap
        venueGeoJSON={project.geojson}
        agents={currentFrame}
        zones={simResult?.zones ?? []}
        barriers={[]}
        staff={[]}
        hotspots={simResult?.hotspots ?? []}
        vis={vis}
      />

      {/* Top bar */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10,
        background: 'rgba(9,9,11,0.88)', backdropFilter: 'blur(14px)',
        borderBottom: '1px solid #27272a',
        display: 'flex', alignItems: 'center', padding: '0 18px', height: 52, gap: 14,
      }}>
        <button
          onClick={() => navigate('/')}
          style={{
            background: 'none', border: '1px solid #3f3f46', borderRadius: 6,
            padding: '5px 12px', color: '#a1a1aa', cursor: 'pointer',
            fontSize: 13, fontFamily: 'inherit',
          }}
        >
          ← Back
        </button>
        <div style={{ width: 1, height: 20, background: '#27272a' }} />
        <span style={{ fontWeight: 700, color: '#f4f4f5', fontSize: 15 }}>{project.name}</span>
        {project.meta?.expected_attendance && (
          <span style={{
            fontSize: 12, color: '#71717a', background: '#18181b',
            border: '1px solid #27272a', borderRadius: 20, padding: '2px 10px',
          }}>
            {Number(project.meta.expected_attendance).toLocaleString()} expected
          </span>
        )}
        <div style={{ marginLeft: 'auto' }}>
          <button
            onClick={handleSaveQuit}
            style={{
              background: '#18181b', border: '1px solid #3f3f46', borderRadius: 6,
              padding: '6px 16px', color: '#a1a1aa', cursor: 'pointer',
              fontSize: 13, fontFamily: 'inherit', fontWeight: 500,
            }}
          >
            Save & Quit
          </button>
        </div>
      </div>

      {/* Left control panel */}
      <ControlPanel
        simParams={simParams}
        onParamsChange={setSimParams}
        vis={vis}
        onToggleVis={key => setVis(v => ({ ...v, [key]: !v[key] }))}
        simRunning={simRunning}
        hasResult={!!simResult}
        onRunSim={handleRunSim}
        beforeAfterLayout={beforeAfterLayout}
        onBeforeAfterLayout={setBeforeAfterLayout}
        beforeAfterSchedule={beforeAfterSchedule}
        onBeforeAfterSchedule={setBeforeAfterSchedule}
        onSetTimes={() => setShowSetTimes(true)}
        addMode={addMode}
        onAddBarrier={() => setAddMode(m => m === 'barrier' ? null : 'barrier')}
        onAddStaff={() => setAddMode(m => m === 'staff' ? null : 'staff')}
      />

      {/* Timeline scrubber — always visible, dimmed until sim runs */}
      <TimelineBar
        meta={project.meta}
        playing={playing}
        onPlayPause={() => setPlaying(p => !p)}
        speed={speed}
        onSpeed={setSpeed}
        value={timelinePct}
        onChange={setTimelinePct}
        disabled={!simResult}
      />

      {/* Set Times overlay */}
      {showSetTimes && (
        <SetTimesOverlay
          stages={stages}
          slots={slots}
          setlist={setlist}
          artists={project.artists ?? []}
          onSave={handleSetTimesSave}
          onClose={() => setShowSetTimes(false)}
        />
      )}
    </div>
  )
}

// ── ControlPanel ──────────────────────────────────────────────────────────────

function PanelSection({ label, children }) {
  return (
    <div style={{ padding: '0 16px 16px' }}>
      <div style={{
        fontSize: 10, fontWeight: 700, color: '#52525b',
        textTransform: 'uppercase', letterSpacing: '0.12em',
        marginBottom: 10, paddingTop: 14,
        borderTop: '1px solid #1c1c1e',
      }}>
        {label}
      </div>
      {children}
    </div>
  )
}

function BeforeAfterToggle({ value, onChange }) {
  return (
    <div style={{ display: 'flex', border: '1px solid #27272a', borderRadius: 5, overflow: 'hidden', marginTop: 6 }}>
      {['before', 'after'].map(opt => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          style={{
            flex: 1, padding: '4px 0',
            background: value === opt ? '#1e3a5f' : 'transparent',
            color: value === opt ? '#60a5fa' : '#52525b',
            border: 'none', cursor: 'pointer', fontFamily: 'inherit',
            fontWeight: 600, fontSize: 10, textTransform: 'capitalize',
          }}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}

function ControlPanel({
  simParams, onParamsChange, vis, onToggleVis,
  simRunning, hasResult, onRunSim,
  beforeAfterLayout, onBeforeAfterLayout,
  beforeAfterSchedule, onBeforeAfterSchedule,
  onSetTimes, addMode, onAddBarrier, onAddStaff,
}) {
  const ticketsMax = simParams.capacity || 80000
  const overCapacity = simParams.tickets_sold > simParams.capacity

  return (
    <div style={{
      position: 'absolute', top: 52, left: 0, bottom: 0, width: PANEL_W,
      background: 'rgba(9,9,11,0.93)', backdropFilter: 'blur(14px)',
      borderRight: '1px solid #27272a',
      zIndex: 10, overflowY: 'auto',
      display: 'flex', flexDirection: 'column',
    }}>
      {/* Run simulation */}
      <div style={{ padding: '16px 16px 0' }}>
        <button
          onClick={onRunSim}
          disabled={simRunning}
          style={{
            width: '100%', background: simRunning ? '#1e3a5f' : '#2563eb',
            color: '#fff', border: 'none', borderRadius: 8,
            padding: '11px 0', fontWeight: 700, fontSize: 14,
            cursor: simRunning ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
            transition: 'background 0.15s',
          }}
        >
          {simRunning ? 'Running…' : hasResult ? 'Rerun Simulation' : 'Run Simulation'}
        </button>
      </div>

      <PanelSection label="Parameters">
        <label style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 14 }}>
          <span style={{ fontSize: 12, color: '#a1a1aa', display: 'flex', justifyContent: 'space-between' }}>
            Capacity
            <span style={{ color: '#71717a', fontSize: 11 }}>hard cap</span>
          </span>
          <input
            type="number"
            value={simParams.capacity}
            onChange={e => onParamsChange(p => ({ ...p, capacity: Number(e.target.value) }))}
            style={{
              background: '#111113', border: '1px solid #3f3f46', borderRadius: 6,
              padding: '6px 10px', color: '#f4f4f5', fontSize: 13,
              fontFamily: 'inherit', outline: 'none', width: '100%', boxSizing: 'border-box',
            }}
          />
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <span style={{ fontSize: 12, display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: overCapacity ? '#ef4444' : '#a1a1aa' }}>Tickets Sold</span>
            <span style={{ color: overCapacity ? '#ef4444' : '#60a5fa', fontVariantNumeric: 'tabular-nums' }}>
              {Number(simParams.tickets_sold).toLocaleString()}
              {overCapacity && ' ⚠'}
            </span>
          </span>
          <input
            type="range"
            min={0} max={ticketsMax} step={100}
            value={Math.min(simParams.tickets_sold, ticketsMax)}
            onChange={e => onParamsChange(p => ({ ...p, tickets_sold: Number(e.target.value) }))}
            style={{ width: '100%', accentColor: overCapacity ? '#ef4444' : '#3b82f6' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#3f3f46' }}>
            <span>0</span>
            <span>{Number(ticketsMax).toLocaleString()}</span>
          </div>
        </label>
      </PanelSection>

      <PanelSection label="Risk Thresholds">
        <label style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 14 }}>
          <span style={{ fontSize: 12, color: '#f97316', display: 'flex', justifyContent: 'space-between' }}>
            Orange density
            <span style={{ color: '#a1a1aa' }}>{simParams.density_orange} p/m²</span>
          </span>
          <input
            type="range" min={1} max={8} step={0.5}
            value={simParams.density_orange}
            onChange={e => onParamsChange(p => ({ ...p, density_orange: Number(e.target.value) }))}
            style={{ width: '100%', accentColor: '#f97316' }}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <span style={{ fontSize: 12, color: '#ef4444', display: 'flex', justifyContent: 'space-between' }}>
            Red density
            <span style={{ color: '#a1a1aa' }}>{simParams.density_red} p/m²</span>
          </span>
          <input
            type="range" min={1} max={8} step={0.5}
            value={simParams.density_red}
            onChange={e => onParamsChange(p => ({ ...p, density_red: Number(e.target.value) }))}
            style={{ width: '100%', accentColor: '#ef4444' }}
          />
        </label>
      </PanelSection>

      <PanelSection label="Schedule">
        <button
          onClick={onSetTimes}
          style={{
            width: '100%', background: '#18181b', border: '1px solid #3f3f46',
            borderRadius: 7, padding: '9px 0', color: '#a1a1aa',
            cursor: 'pointer', fontFamily: 'inherit', fontSize: 13, fontWeight: 500,
          }}
        >
          Set Times →
        </button>
      </PanelSection>

      <PanelSection label="Interventions">
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={onAddBarrier}
            style={{
              flex: 1, background: addMode === 'barrier' ? '#1e3a5f' : '#18181b',
              border: `1px solid ${addMode === 'barrier' ? '#2563eb' : '#3f3f46'}`,
              borderRadius: 7, padding: '8px 0',
              color: addMode === 'barrier' ? '#60a5fa' : '#a1a1aa',
              cursor: 'pointer', fontFamily: 'inherit', fontSize: 12, fontWeight: 500,
            }}
          >
            + Barrier
          </button>
          <button
            onClick={onAddStaff}
            style={{
              flex: 1, background: addMode === 'staff' ? '#1e3a5f' : '#18181b',
              border: `1px solid ${addMode === 'staff' ? '#2563eb' : '#3f3f46'}`,
              borderRadius: 7, padding: '8px 0',
              color: addMode === 'staff' ? '#60a5fa' : '#a1a1aa',
              cursor: 'pointer', fontFamily: 'inherit', fontSize: 12, fontWeight: 500,
            }}
          >
            + Staff
          </button>
        </div>
        {addMode && (
          <div style={{ fontSize: 11, color: '#52525b', textAlign: 'center', marginTop: 8 }}>
            Click on the map to place a {addMode}
          </div>
        )}
      </PanelSection>

      <PanelSection label="Optimize">
        <div style={{ marginBottom: 12 }}>
          <button
            style={{
              width: '100%', background: '#18181b', border: '1px solid #3f3f46',
              borderRadius: 7, padding: '9px 12px',
              color: '#a1a1aa', cursor: 'pointer', fontFamily: 'inherit',
              fontSize: 12, fontWeight: 500, textAlign: 'left',
            }}
          >
            Optimize Layout ▶
          </button>
          <BeforeAfterToggle value={beforeAfterLayout} onChange={onBeforeAfterLayout} />
        </div>
        <div>
          <button
            style={{
              width: '100%', background: '#18181b', border: '1px solid #3f3f46',
              borderRadius: 7, padding: '9px 12px',
              color: '#a1a1aa', cursor: 'pointer', fontFamily: 'inherit',
              fontSize: 12, fontWeight: 500, textAlign: 'left',
            }}
          >
            Optimize Schedule ▶
          </button>
          <BeforeAfterToggle value={beforeAfterSchedule} onChange={onBeforeAfterSchedule} />
        </div>
      </PanelSection>

      <PanelSection label="Layers">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {Object.entries(vis).map(([key, on]) => (
            <button
              key={key}
              onClick={() => onToggleVis(key)}
              style={{
                background: on ? '#1e3a5f' : '#18181b',
                color: on ? '#60a5fa' : '#52525b',
                border: `1px solid ${on ? '#2563eb' : '#27272a'}`,
                borderRadius: 5, padding: '3px 9px', fontSize: 11,
                cursor: 'pointer', fontFamily: 'inherit', fontWeight: 600,
              }}
            >
              {key.charAt(0).toUpperCase() + key.slice(1)}
            </button>
          ))}
        </div>
      </PanelSection>
    </div>
  )
}

// ── TimelineBar ───────────────────────────────────────────────────────────────

const SPEEDS = [0.25, 0.5, 1, 2, 4]

function TimelineBar({ meta, playing, onPlayPause, speed, onSpeed, value, onChange, disabled }) {
  function pctToTime(pct) {
    if (!meta?.start_time || !meta?.end_time) return '--:--'
    const parse = t => { const [h, m] = t.split(':').map(Number); return h * 60 + (m || 0) }
    let start = parse(meta.start_time), end = parse(meta.end_time)
    if (end <= start) end += 24 * 60
    const minutes = start + pct * (end - start)
    const h = Math.floor(minutes / 60) % 24
    const m = Math.floor(minutes % 60)
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
  }

  return (
    <div style={{
      position: 'absolute', bottom: 0, left: PANEL_W, right: 0, zIndex: 10,
      background: 'rgba(9,9,11,0.93)', backdropFilter: 'blur(14px)',
      borderTop: '1px solid #27272a',
      padding: '10px 18px',
      display: 'flex', alignItems: 'center', gap: 12,
      opacity: disabled ? 0.32 : 1,
      pointerEvents: disabled ? 'none' : 'auto',
      transition: 'opacity 0.2s',
    }}>
      <button
        onClick={onPlayPause}
        style={{
          background: 'none', border: '1px solid #3f3f46', borderRadius: 6,
          color: '#a1a1aa', cursor: 'pointer', padding: '4px 11px',
          fontSize: 14, fontFamily: 'inherit', lineHeight: 1, flexShrink: 0,
        }}
      >
        {playing ? '⏸' : '▶'}
      </button>

      <input
        type="range" min={0} max={1} step={0.001}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ flex: 1, accentColor: '#3b82f6' }}
      />

      <span style={{ fontSize: 12, color: '#71717a', fontVariantNumeric: 'tabular-nums', minWidth: 38, flexShrink: 0 }}>
        {pctToTime(value)}
      </span>

      <select
        value={speed}
        onChange={e => onSpeed(Number(e.target.value))}
        style={{
          background: '#18181b', border: '1px solid #3f3f46', borderRadius: 5,
          color: '#a1a1aa', fontSize: 11, padding: '3px 6px',
          fontFamily: 'inherit', cursor: 'pointer', flexShrink: 0,
        }}
      >
        {SPEEDS.map(s => <option key={s} value={s}>{s}x</option>)}
      </select>

      {disabled && (
        <span style={{ fontSize: 11, color: '#3f3f46', flexShrink: 0 }}>
          Run simulation to enable playback
        </span>
      )}
    </div>
  )
}

// ── SetTimesOverlay ───────────────────────────────────────────────────────────

function SetTimesOverlay({ stages, slots, setlist, artists, onSave, onClose }) {
  const [schedule, setSchedule] = useState(() => setlistToSchedule(setlist, stages, slots))
  const [draggingArtist, setDraggingArtist] = useState(null)
  const [dragOverCell, setDragOverCell] = useState(null)
  const [saving, setSaving] = useState(false)

  const assignedSet = new Set(
    Object.values(schedule).flatMap(s => Object.values(s).map(c => c.artist).filter(Boolean))
  )
  const unassigned = artists.filter(a => a && !assignedSet.has(a))

  function assignArtist(stageId, slotIdx, artist) {
    if (schedule[stageId]?.[slotIdx]?.locked) return
    setSchedule(prev => {
      const next = JSON.parse(JSON.stringify(prev))
      for (const sid of Object.keys(next)) {
        for (const idx of Object.keys(next[sid])) {
          if (next[sid][idx].artist === artist) next[sid][idx].artist = null
        }
      }
      next[stageId][slotIdx].artist = artist
      return next
    })
  }

  function toggleLock(stageId, slotIdx) {
    if (!schedule[stageId]?.[slotIdx]?.artist) return
    setSchedule(prev => ({
      ...prev,
      [stageId]: {
        ...prev[stageId],
        [slotIdx]: { ...prev[stageId][slotIdx], locked: !prev[stageId][slotIdx].locked },
      },
    }))
  }

  async function handleSave() {
    setSaving(true)
    await onSave(scheduleToSetlist(schedule, stages, slots))
    setSaving(false)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 50,
      background: 'rgba(0,0,0,0.88)', backdropFilter: 'blur(6px)',
      display: 'flex', flexDirection: 'column',
      fontFamily: 'Inter, system-ui, sans-serif', color: '#f4f4f5',
    }}>
      {/* Header */}
      <div style={{
        height: 56, borderBottom: '1px solid #27272a',
        background: 'rgba(9,9,11,0.97)',
        display: 'flex', alignItems: 'center', padding: '0 24px', gap: 16, flexShrink: 0,
      }}>
        <span style={{ fontWeight: 700, fontSize: 16 }}>Set Times</span>
        <span style={{ fontSize: 12, color: '#52525b' }}>
          Double-click a slot to lock/unlock · locked artists won't be moved by the optimizer
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: '1px solid #3f3f46', borderRadius: 6,
              padding: '6px 16px', color: '#a1a1aa', cursor: 'pointer',
              fontSize: 13, fontFamily: 'inherit',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave} disabled={saving}
            style={{
              background: '#2563eb', border: 'none', borderRadius: 6,
              padding: '6px 18px', color: '#fff',
              cursor: saving ? 'not-allowed' : 'pointer',
              fontSize: 13, fontFamily: 'inherit', fontWeight: 600,
            }}
          >
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Sidebar */}
        <div style={{
          width: 182, flexShrink: 0,
          background: 'rgba(9,9,11,0.97)',
          borderRight: '1px solid #1c1c1e',
          padding: 16, overflowY: 'auto',
        }}>
          <div style={{
            fontSize: 10, fontWeight: 700, color: '#52525b',
            textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 12,
          }}>
            Unassigned ({unassigned.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {unassigned.map(artist => (
              <div
                key={artist}
                draggable
                onDragStart={e => {
                  e.dataTransfer.setData('artist', artist)
                  e.dataTransfer.effectAllowed = 'move'
                  setDraggingArtist(artist)
                }}
                onDragEnd={() => setDraggingArtist(null)}
                style={{
                  padding: '6px 10px', background: '#27272a', border: '1px solid #3f3f46',
                  borderRadius: 6, fontSize: 12, cursor: 'grab', color: '#e4e4e7',
                  opacity: draggingArtist === artist ? 0.35 : 1,
                  userSelect: 'none', whiteSpace: 'nowrap',
                  overflow: 'hidden', textOverflow: 'ellipsis',
                }}
              >
                {artist}
              </div>
            ))}
            {unassigned.length === 0 && (
              <div style={{ color: '#52525b', fontSize: 12, textAlign: 'center', paddingTop: 12 }}>
                All assigned
              </div>
            )}
          </div>
        </div>

        {/* Schedule grid */}
        <div style={{ flex: 1, overflowX: 'auto', overflowY: 'auto', padding: '16px 20px' }}>
          {stages.length === 0 ? (
            <div style={{ color: '#52525b', fontSize: 13, paddingTop: 24 }}>
              No stages found in venue GeoJSON.
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 10, minWidth: stages.length * 190 }}>
              {stages.map(stage => (
                <div key={stage.id} style={{ flex: 1, minWidth: 180 }}>
                  <div style={{
                    textAlign: 'center', padding: '7px 0', marginBottom: 8,
                    borderBottom: `2px solid ${stage.color}`,
                    fontWeight: 800, fontSize: 12, color: stage.color,
                    textTransform: 'uppercase', letterSpacing: '0.1em',
                  }}>
                    {stage.name}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {slots.map((slot, idx) => {
                      const cell = schedule[stage.id]?.[idx]
                      const artist = cell?.artist
                      const locked = cell?.locked
                      const cellKey = `${stage.id}:${idx}`
                      const isOver = dragOverCell === cellKey && !locked
                      let bg = '#0d0d0f', border = '#1c1c1e'
                      if (locked) { bg = '#1a1200'; border = '#d97706' }
                      else if (artist) { bg = '#0c1a2e'; border = '#2563eb' }
                      else if (isOver) { bg = '#0f1f3d'; border = '#60a5fa' }
                      return (
                        <div
                          key={idx}
                          onDragOver={e => { e.preventDefault(); setDragOverCell(cellKey) }}
                          onDragLeave={() => setDragOverCell(c => c === cellKey ? null : c)}
                          onDrop={e => {
                            e.preventDefault(); setDragOverCell(null)
                            const a = e.dataTransfer.getData('artist')
                            if (a) assignArtist(stage.id, idx, a)
                          }}
                          onDoubleClick={() => toggleLock(stage.id, idx)}
                          title={artist ? (locked ? 'Double-click to unlock' : 'Double-click to lock') : 'Drag artist here'}
                          style={{
                            border: `1px solid ${border}`, borderRadius: 6,
                            padding: '5px 8px', background: bg, minHeight: 52,
                            transition: 'border-color 0.1s, background 0.1s',
                            display: 'flex', flexDirection: 'column', gap: 3,
                            cursor: locked ? 'not-allowed' : 'default',
                          }}
                        >
                          <div style={{ fontSize: 10, color: '#3f3f46', fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>
                            {slot.label}
                          </div>
                          {artist ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 5, minWidth: 0 }}>
                              <span style={{
                                fontSize: 12, fontWeight: 600,
                                color: locked ? '#fcd34d' : '#bfdbfe',
                                flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                              }}>
                                {artist}
                              </span>
                              {locked && <span style={{ fontSize: 11, flexShrink: 0 }}>🔒</span>}
                            </div>
                          ) : (
                            <div style={{ fontSize: 11, color: '#2a2a2e', fontStyle: 'italic' }}>
                              {isOver ? 'Drop here' : 'empty'}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
