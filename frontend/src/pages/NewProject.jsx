import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import GeoJSONPreview from '../components/GeoJSONPreview.jsx'
import { api } from '../api/client.js'

// ── Shared styles ──────────────────────────────────────────────────────────────

const S = {
  primaryBtn: {
    background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 8,
    padding: '10px 24px', fontWeight: 600, fontSize: 14, cursor: 'pointer',
    fontFamily: 'inherit',
  },
  ghostBtn: {
    background: 'transparent', color: '#a1a1aa', border: '1px solid #3f3f46',
    borderRadius: 8, padding: '10px 24px', fontWeight: 500, fontSize: 14,
    cursor: 'pointer', fontFamily: 'inherit',
  },
  input: {
    background: '#111113', border: '1px solid #3f3f46', borderRadius: 6,
    padding: '8px 12px', color: '#f4f4f5', fontSize: 14,
    outline: 'none', fontFamily: 'inherit', width: '100%', boxSizing: 'border-box',
  },
  label: {
    display: 'flex', flexDirection: 'column', gap: 6,
    fontSize: 13, color: '#a1a1aa', fontWeight: 500,
  },
  card: {
    background: '#18181b', border: '1px solid #27272a',
    borderRadius: 10, padding: 24,
  },
}

const STAGE_COLORS = {
  hard: '#ef4444', harder: '#f97316', green: '#22c55e',
  purple: '#a855f7', pink: '#ec4899', beatbox: '#22d3ee', locals_only: '#fbbf24',
}

function generateSlots(startTime, endTime) {
  const parse = t => {
    const [h, m] = t.split(':').map(Number)
    return h * 60 + (m || 0)
  }
  let start = parse(startTime || '12:00')
  let end = parse(endTime || '00:00')
  if (end <= start) end += 24 * 60

  const slots = []
  for (let t = start; t < end; t += 60) {
    const h1 = Math.floor(t / 60) % 24
    const h2 = Math.floor((t + 60) / 60) % 24
    slots.push({
      index: slots.length,
      label: `${h1 === 0 ? 12 : h1 > 12 ? h1 - 12 : h1}:00 ${h1 >= 12 ? 'PM' : 'AM'} – ${h2 === 0 ? 12 : h2 > 12 ? h2 - 12 : h2}:00 ${h2 >= 12 ? 'PM' : 'AM'}`,
      start: `${String(h1).padStart(2, '0')}:00`,
      end: `${String(h2).padStart(2, '0')}:00`,
    })
  }
  return slots // ascending: earliest slot at top, headliners at bottom
}

// ── Main wizard component ──────────────────────────────────────────────────────

export default function NewProject() {
  const [step, setStep] = useState(0)
  const [geojson, setGeojson] = useState(null)
  const [stages, setStages] = useState([])
  const [info, setInfo] = useState({
    name: '', start_time: '12:00', end_time: '00:00',
    max_occupancy: 80000, expected_attendance: 75000,
  })
  const [artists, setArtists] = useState([''])
  const [schedule, setSchedule] = useState({}) // { stageId: { slotIdx: { artist, locked } } }
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()

  const slots = generateSlots(info.start_time, info.end_time)

  function handleGeoJSONUpload(e) {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = ev => {
      try {
        const parsed = JSON.parse(ev.target.result)
        const stageFeats = (parsed.features ?? []).filter(f => f.properties?.type === 'stage')
        setStages(stageFeats.map(f => ({
          id: f.properties.stage_id ?? f.properties.id ?? f.properties.name?.toLowerCase().replace(/\s+/g, '_') ?? 'unknown',
          name: f.properties.name ?? f.properties.stage_id ?? 'Stage',
          color: STAGE_COLORS[f.properties.stage_id] ?? '#888',
        })))
        setGeojson(parsed)
      } catch {
        alert('Invalid GeoJSON file — please upload a valid .geojson')
      }
    }
    reader.readAsText(file)
  }

  function initSchedule() {
    const fresh = {}
    stages.forEach(stage => {
      fresh[stage.id] = {}
      slots.forEach((_, idx) => {
        fresh[stage.id][idx] = { artist: null, locked: false }
      })
    })
    setSchedule(fresh)
  }

  function goNext() {
    if (step === 1) initSchedule()
    setStep(s => s + 1)
  }

  const assignedSet = new Set(
    Object.values(schedule).flatMap(stage =>
      Object.values(stage).map(s => s.artist).filter(Boolean)
    )
  )
  const unassigned = artists.filter(a => a.trim() && !assignedSet.has(a.trim()))

  function assignArtist(stageId, slotIdx, artist) {
    if (schedule[stageId]?.[slotIdx]?.locked) return
    setSchedule(prev => {
      const next = JSON.parse(JSON.stringify(prev))
      // Clear artist's previous slot
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

  function clearAll() {
    setSchedule(prev => {
      const next = JSON.parse(JSON.stringify(prev))
      for (const sid of Object.keys(next)) {
        for (const idx of Object.keys(next[sid])) {
          next[sid][idx] = { artist: null, locked: false }
        }
      }
      return next
    })
  }

  async function handleCreate() {
    setSubmitting(true)
    try {
      const setlist = []
      for (const stage of stages) {
        for (let i = 0; i < slots.length; i++) {
          const slotData = schedule[stage.id]?.[i]
          if (slotData?.artist) {
            setlist.push({
              artist: slotData.artist,
              stage: stage.id,
              start: slots[i].start,
              end: slots[i].end,
              locked: slotData.locked,
            })
          }
        }
      }

      const project = await api.createProject({
        name: info.name || 'Untitled Festival',
        geojson,
        meta: {
          start_time: info.start_time,
          end_time: info.end_time,
          max_occupancy: Number(info.max_occupancy),
          expected_attendance: Number(info.expected_attendance),
        },
        artists: artists.filter(a => a.trim()),
        setlist,
      })

      navigate(`/projects/${project.id}`)
    } catch (err) {
      alert('Failed to create project: ' + err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const STEP_LABELS = ['Upload Map', 'Artists & Info', 'Stage Schedule']

  return (
    <div style={{ minHeight: '100vh', background: '#09090b', color: '#f4f4f5', fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* Header */}
      <div style={{
        borderBottom: '1px solid #27272a', padding: '0 32px',
        display: 'flex', alignItems: 'center', gap: 16, height: 56,
        position: 'sticky', top: 0, zIndex: 20,
        background: 'rgba(9,9,11,0.95)', backdropFilter: 'blur(12px)',
      }}>
        <button onClick={() => navigate('/')} style={{
          background: 'none', border: '1px solid #3f3f46', borderRadius: 6,
          padding: '5px 12px', color: '#a1a1aa', cursor: 'pointer', fontSize: 13,
          fontFamily: 'inherit',
        }}>
          ← Home
        </button>
        <span style={{ fontWeight: 700, fontSize: 16 }}>New Project</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          {STEP_LABELS.map((label, i) => (
            <div key={i} style={{
              padding: '4px 14px', borderRadius: 20, fontSize: 12, fontWeight: 600,
              background: step === i ? '#3b82f6' : step > i ? '#1e3a5f' : '#1c1c1e',
              color: step === i ? '#fff' : step > i ? '#60a5fa' : '#52525b',
              border: `1px solid ${step === i ? '#3b82f6' : step > i ? '#1d4ed8' : '#27272a'}`,
            }}>
              {i + 1}. {label}
            </div>
          ))}
        </div>
      </div>

      {/* Step content */}
      <div style={{ maxWidth: '100%', padding: '48px 48px' }}>
        {step === 0 && (
          <StepUpload
            geojson={geojson} stages={stages}
            onUpload={handleGeoJSONUpload}
            onNext={goNext}
          />
        )}
        {step === 1 && (
          <StepArtists
            info={info} onInfoChange={setInfo}
            artists={artists} onSetArtists={setArtists}
            onBack={() => setStep(0)} onNext={goNext}
          />
        )}
        {step === 2 && (
          <StepSchedule
            stages={stages} slots={slots}
            schedule={schedule} unassigned={unassigned}
            onAssign={assignArtist} onLock={toggleLock}
            onBack={() => setStep(1)}
            onCreate={handleCreate} submitting={submitting}
            onClearAll={clearAll}
          />
        )}
      </div>
    </div>
  )
}

// ── TimePicker ────────────────────────────────────────────────────────────────

function TimePicker({ value, onChange }) {
  const [h24, m] = (value || '12:00').split(':').map(Number)
  const isPM = h24 >= 12
  const h12 = h24 === 0 ? 12 : h24 > 12 ? h24 - 12 : h24
  const hours = Array.from({ length: 12 }, (_, i) => i + 1)
  const minutes = [0, 15, 30, 45]

  function update(newH12, newMin, newPM) {
    let h = newH12 === 12 ? 0 : newH12
    if (newPM) h += 12
    onChange(`${String(h).padStart(2, '0')}:${String(newMin).padStart(2, '0')}`)
  }

  const selStyle = { ...S.input, width: 'auto', minWidth: 56, cursor: 'pointer' }

  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <select value={h12} onChange={e => update(Number(e.target.value), m, isPM)} style={selStyle}>
        {hours.map(hr => <option key={hr} value={hr}>{hr}</option>)}
      </select>
      <span style={{ color: '#71717a', fontSize: 16 }}>:</span>
      <select value={m - (m % 15)} onChange={e => update(h12, Number(e.target.value), isPM)} style={selStyle}>
        {minutes.map(min => <option key={min} value={min}>{String(min).padStart(2, '0')}</option>)}
      </select>
      <select value={isPM ? 'PM' : 'AM'} onChange={e => update(h12, m, e.target.value === 'PM')} style={selStyle}>
        <option value="AM">AM</option>
        <option value="PM">PM</option>
      </select>
    </div>
  )
}

// ── Step 0: Upload GeoJSON ─────────────────────────────────────────────────────

function StepUpload({ geojson, stages, onUpload, onNext }) {
  const inputRef = useRef(null)
  const [draggingOver, setDraggingOver] = useState(false)

  function handleDrop(e) {
    e.preventDefault()
    setDraggingOver(false)
    const file = e.dataTransfer.files[0]
    if (file) onUpload({ target: { files: [file] } })
  }

  return (
    <div>
      <h2 style={{ fontSize: 26, fontWeight: 700, margin: '0 0 8px' }}>Upload Venue Map</h2>
      <p style={{ color: '#71717a', margin: '0 0 36px', fontSize: 14 }}>
        Upload a GeoJSON file with your festival grounds. Stages, walkable areas, obstacles, and gates will be extracted automatically.
      </p>

      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDraggingOver(true) }}
        onDragLeave={() => setDraggingOver(false)}
        onDrop={handleDrop}
        style={{
          border: `2px dashed ${geojson ? '#22c55e' : draggingOver ? '#3b82f6' : '#3f3f46'}`,
          borderRadius: 12, padding: '40px 32px', textAlign: 'center', cursor: 'pointer',
          background: geojson ? '#0d1f0d' : draggingOver ? '#0f1f3d' : '#111113',
          transition: 'all 0.15s',
        }}
      >
        <input
          ref={inputRef} type="file" accept=".geojson,.json"
          onChange={onUpload} style={{ display: 'none' }}
        />
        {geojson ? (
          <>
            <div style={{ fontSize: 28, marginBottom: 8 }}>✓</div>
            <div style={{ fontWeight: 700, color: '#22c55e', marginBottom: 6 }}>GeoJSON loaded</div>
            <div style={{ color: '#71717a', fontSize: 13 }}>
              {stages.length} stage{stages.length !== 1 ? 's' : ''} detected:&nbsp;
              {stages.map(s => s.name).join(', ')}
            </div>
            <div style={{ color: '#52525b', fontSize: 12, marginTop: 6 }}>Click to replace</div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 36, marginBottom: 12, color: '#3f3f46' }}>📁</div>
            <div style={{ fontWeight: 600, color: '#f4f4f5', marginBottom: 6 }}>
              Click or drag to upload venue GeoJSON
            </div>
            <div style={{ color: '#52525b', fontSize: 13 }}>.geojson or .json</div>
          </>
        )}
      </div>

      {geojson && (
        <div style={{ marginTop: 28, borderRadius: 12, overflow: 'hidden' }}>
          <GeoJSONPreview geojson={geojson} width={896} height={320} />
        </div>
      )}

      <div style={{ marginTop: 32, display: 'flex', justifyContent: 'flex-end' }}>
        <button
          onClick={onNext} disabled={!geojson}
          style={{ ...S.primaryBtn, opacity: geojson ? 1 : 0.4, cursor: geojson ? 'pointer' : 'not-allowed' }}
        >
          Continue →
        </button>
      </div>
    </div>
  )
}

// ── Step 1: Artists & Festival Info ───────────────────────────────────────────

function StepArtists({ info, onInfoChange, artists, onSetArtists, onBack, onNext }) {
  const validCount = artists.filter(a => a.trim()).length

  function setArtist(idx, val) {
    onSetArtists(prev => prev.map((a, i) => (i === idx ? val : a)))
  }

  function removeArtist(idx) {
    onSetArtists(prev => prev.filter((_, i) => i !== idx))
  }

  function handlePaste(idx, e) {
    const text = e.clipboardData.getData('text')
    const lines = text.split(/[\n,]/).map(l => l.trim()).filter(Boolean)
    if (lines.length > 1) {
      e.preventDefault()
      onSetArtists(prev => {
        const next = [...prev]
        next.splice(idx, 1, ...lines)
        return next
      })
    }
  }

  return (
    <div>
      <h2 style={{ fontSize: 26, fontWeight: 700, margin: '0 0 8px' }}>Artists & Festival Info</h2>
      <p style={{ color: '#71717a', margin: '0 0 36px', fontSize: 14 }}>
        Enter your lineup and festival details. You can paste a comma-separated or newline-separated list of artist names into any field.
      </p>

      <div style={{ ...S.card, marginBottom: 28 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#71717a', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 20 }}>
          Festival Details
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
          <label style={{ ...S.label, gridColumn: '1 / -1' }}>
            Festival Name
            <input
              value={info.name}
              onChange={e => onInfoChange(p => ({ ...p, name: e.target.value }))}
              placeholder="e.g. HARD Summer 2026"
              style={S.input}
            />
          </label>
          <label style={S.label}>
            Start Time
            <TimePicker value={info.start_time} onChange={v => onInfoChange(p => ({ ...p, start_time: v }))} />
          </label>
          <label style={S.label}>
            End Time
            <TimePicker value={info.end_time} onChange={v => onInfoChange(p => ({ ...p, end_time: v }))} />
          </label>
          <label style={S.label}>
            Max Occupancy
            <input type="number" value={info.max_occupancy}
              onChange={e => onInfoChange(p => ({ ...p, max_occupancy: e.target.value }))}
              style={S.input} />
          </label>
        </div>
      </div>

      <div style={S.card}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#71717a', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 20 }}>
          Lineup — {validCount} artist{validCount !== 1 ? 's' : ''}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
          {artists.map((artist, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                value={artist}
                onChange={e => setArtist(i, e.target.value)}
                onPaste={e => handlePaste(i, e)}
                placeholder={`Artist ${i + 1}`}
                style={{ ...S.input, flex: 1 }}
              />
              {artists.length > 1 && (
                <button
                  onClick={() => removeArtist(i)}
                  style={{
                    background: '#27272a', color: '#ef4444', border: 'none',
                    borderRadius: 6, width: 32, height: 36, cursor: 'pointer',
                    fontSize: 16, fontFamily: 'inherit', flexShrink: 0,
                  }}
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </div>
        <button
          onClick={() => onSetArtists(prev => [...prev, ''])}
          style={S.ghostBtn}
        >
          + Add Artist
        </button>
      </div>

      <div style={{ marginTop: 32, display: 'flex', justifyContent: 'space-between' }}>
        <button onClick={onBack} style={S.ghostBtn}>← Back</button>
        <button
          onClick={onNext} disabled={validCount === 0}
          style={{ ...S.primaryBtn, opacity: validCount > 0 ? 1 : 0.4, cursor: validCount > 0 ? 'pointer' : 'not-allowed' }}
        >
          Continue →
        </button>
      </div>
    </div>
  )
}

// ── Step 2: Stage Schedule ─────────────────────────────────────────────────────

function StepSchedule({ stages, slots, schedule, unassigned, onAssign, onLock, onBack, onCreate, submitting, onClearAll }) {
  const [draggingArtist, setDraggingArtist] = useState(null)
  const [dragOverCell, setDragOverCell] = useState(null) // `${stageId}:${slotIdx}`
  const [showModal, setShowModal] = useState(false)

  function handleCreate() {
    if (unassigned.length > 0) setShowModal(true)
    else onCreate()
  }

  return (
    <div>
      <h2 style={{ fontSize: 26, fontWeight: 700, margin: '0 0 8px' }}>Stage Schedule</h2>
      <p style={{ color: '#71717a', margin: '0 0 28px', fontSize: 14 }}>
        Drag artists from the sidebar into time slots. Earliest times are at the top — headliners go at the bottom. Double-click a filled slot to lock it — locked artists won't be moved by the optimizer.
      </p>

      <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
        {/* Sidebar */}
        <div style={{
          width: 172, flexShrink: 0,
          ...S.card, position: 'sticky', top: 72,
          maxHeight: 'calc(100vh - 160px)', overflowY: 'auto',
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, color: '#71717a', textTransform: 'uppercase',
            letterSpacing: '0.1em', marginBottom: 12,
          }}>
            Unassigned ({unassigned.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {unassigned.map(artist => (
              <ArtistChip
                key={artist} artist={artist}
                dragging={draggingArtist === artist}
                onDragStart={() => setDraggingArtist(artist)}
                onDragEnd={() => setDraggingArtist(null)}
              />
            ))}
            {unassigned.length === 0 && (
              <div style={{ color: '#52525b', fontSize: 12, textAlign: 'center', padding: '12px 0' }}>
                All artists assigned
              </div>
            )}
          </div>
        </div>

        {/* Schedule grid */}
        <div style={{ flex: 1, paddingBottom: 8 }}>
          <div style={{ display: 'flex', gap: 10 }}>
            {stages.map(stage => (
              <div key={stage.id} style={{ flex: 1, minWidth: 0 }}>
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

                    return (
                      <SlotCell
                        key={idx}
                        slot={slot}
                        artist={artist}
                        locked={locked}
                        isOver={isOver}
                        onDragOver={e => { e.preventDefault(); setDragOverCell(cellKey) }}
                        onDragLeave={() => setDragOverCell(c => c === cellKey ? null : c)}
                        onDrop={e => {
                          e.preventDefault()
                          setDragOverCell(null)
                          const a = e.dataTransfer.getData('artist')
                          if (a) onAssign(stage.id, idx, a)
                        }}
                        onDoubleClick={() => onLock(stage.id, idx)}
                      />
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 32, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <button onClick={onBack} style={S.ghostBtn}>← Back</button>
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onClearAll}
            style={{ ...S.ghostBtn, borderColor: '#7f1d1d', color: '#f87171' }}
          >
            Clear All
          </button>
          <button
            onClick={handleCreate} disabled={submitting}
            style={{ ...S.primaryBtn, opacity: submitting ? 0.6 : 1, cursor: submitting ? 'not-allowed' : 'pointer' }}
          >
            {submitting ? 'Creating…' : 'Create Project →'}
          </button>
        </div>
      </div>

      {showModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 100,
          background: 'rgba(0,0,0,0.78)', backdropFilter: 'blur(4px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            background: '#18181b', border: '1px solid #27272a', borderRadius: 14,
            padding: 32, maxWidth: 460, width: '90%',
          }}>
            <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 10, color: '#f4f4f5' }}>
              {unassigned.length} artist{unassigned.length > 1 ? 's' : ''} not assigned
            </div>
            <p style={{ color: '#a1a1aa', fontSize: 14, margin: '0 0 12px' }}>
              The following artists haven't been placed in a time slot:
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '0 0 16px', maxHeight: 120, overflowY: 'auto' }}>
              {unassigned.map(a => (
                <span key={a} style={{
                  background: '#27272a', color: '#e4e4e7', borderRadius: 6,
                  padding: '3px 10px', fontSize: 12,
                }}>
                  {a}
                </span>
              ))}
            </div>
            <p style={{ color: '#71717a', fontSize: 13, margin: '0 0 24px' }}>
              The algorithm will auto-fill remaining slots. You can also go back and assign them manually.
            </p>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button onClick={() => setShowModal(false)} style={S.ghostBtn}>Cancel</button>
              <button
                onClick={() => { setShowModal(false); onCreate() }}
                style={S.primaryBtn}
              >
                Proceed Anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ArtistChip({ artist, dragging, onDragStart, onDragEnd }) {
  return (
    <div
      draggable
      onDragStart={e => { e.dataTransfer.setData('artist', artist); e.dataTransfer.effectAllowed = 'move'; onDragStart() }}
      onDragEnd={onDragEnd}
      style={{
        padding: '6px 10px',
        background: '#27272a',
        border: '1px solid #3f3f46',
        borderRadius: 6,
        fontSize: 12,
        cursor: 'grab',
        color: '#e4e4e7',
        opacity: dragging ? 0.35 : 1,
        transition: 'opacity 0.1s',
        userSelect: 'none',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
    >
      {artist}
    </div>
  )
}

function SlotCell({ slot, artist, locked, isOver, onDragOver, onDragLeave, onDrop, onDoubleClick }) {
  let bg = '#0d0d0f'
  let border = '#1c1c1e'
  if (locked) { bg = '#1a1200'; border = '#d97706' }
  else if (artist) { bg = '#0c1a2e'; border = '#2563eb' }
  else if (isOver) { bg = '#0f1f3d'; border = '#60a5fa' }

  return (
    <div
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onDoubleClick={onDoubleClick}
      title={artist ? (locked ? 'Double-click to unlock' : 'Double-click to lock') : 'Drag an artist here'}
      style={{
        border: `1px solid ${border}`,
        borderRadius: 6,
        padding: '5px 8px',
        background: bg,
        minHeight: 52,
        transition: 'border-color 0.1s, background 0.1s',
        display: 'flex',
        flexDirection: 'column',
        gap: 3,
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
}
