import { useState } from 'react'

const STAGES = ['hard', 'worldwide', 'bass_camp', 'pink', 'harder', 'outloud', 'b2b']

const DEFAULT_SETLIST = [
  { artist: 'Fisher',             stage: 'hard',      start: '14:00', end: '15:00' },
  { artist: 'REZZ',               stage: 'worldwide', start: '14:00', end: '15:00' },
  { artist: 'Chris Lake',         stage: 'bass_camp', start: '15:00', end: '16:00' },
  { artist: 'John Summit',        stage: 'pink',      start: '15:00', end: '16:00' },
  { artist: 'Charlotte de Witte', stage: 'worldwide', start: '21:00', end: '22:30' },
  { artist: 'SKRILLEX',           stage: 'hard',      start: '22:00', end: '00:00' },
]

export default function ScheduleEditor({ setlist, onChange, onOptimize, isOptimizing, optimizeResult }) {
  const [newRow, setNewRow] = useState({ artist: '', stage: 'hard', start: '12:00', end: '13:00' })
  const [headliners, setHeadliners] = useState(['SKRILLEX', 'Charlotte de Witte'])

  function updateRow(i, field, value) {
    const next = setlist.map((r, idx) => idx === i ? { ...r, [field]: value } : r)
    onChange(next)
  }

  function removeRow(i) {
    onChange(setlist.filter((_, idx) => idx !== i))
  }

  function addRow() {
    if (!newRow.artist.trim()) return
    onChange([...setlist, { ...newRow }])
    setNewRow({ artist: '', stage: 'hard', start: '12:00', end: '13:00' })
  }

  function loadDefaults() {
    onChange(DEFAULT_SETLIST)
  }

  return (
    <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Table */}
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #3f3f46' }}>
            {['Artist', 'Stage', 'Start', 'End', ''].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '4px 8px', color: '#71717a', fontSize: 11, fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {setlist.map((row, i) => (
            <tr key={i} style={{ borderBottom: '1px solid #27272a' }}>
              <td style={{ padding: '4px 4px' }}>
                <input value={row.artist} onChange={e => updateRow(i, 'artist', e.target.value)}
                  style={{ width: '100%', background: 'transparent', border: 'none', borderBottom: '1px solid transparent' }}
                  onFocus={e => e.target.style.borderBottomColor = '#3b82f6'}
                  onBlur={e => e.target.style.borderBottomColor = 'transparent'}
                />
              </td>
              <td style={{ padding: '4px 4px' }}>
                <select value={row.stage} onChange={e => updateRow(i, 'stage', e.target.value)}
                  style={{ background: 'transparent', border: 'none', color: '#a1a1aa', fontSize: 12 }}>
                  {STAGES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </td>
              <td style={{ padding: '4px 4px' }}>
                <input type="time" value={row.start} onChange={e => updateRow(i, 'start', e.target.value)}
                  style={{ background: 'transparent', border: 'none', color: '#a1a1aa', width: 80 }} />
              </td>
              <td style={{ padding: '4px 4px' }}>
                <input type="time" value={row.end} onChange={e => updateRow(i, 'end', e.target.value)}
                  style={{ background: 'transparent', border: 'none', color: '#a1a1aa', width: 80 }} />
              </td>
              <td style={{ padding: '4px 4px' }}>
                <button onClick={() => removeRow(i)}
                  style={{ background: 'none', color: '#71717a', fontSize: 14, padding: '0 4px' }}>✕</button>
              </td>
            </tr>
          ))}
          {/* Add row */}
          <tr>
            <td style={{ padding: '6px 4px' }}>
              <input placeholder="Artist name" value={newRow.artist}
                onChange={e => setNewRow(r => ({ ...r, artist: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && addRow()}
                style={{ width: '100%' }} />
            </td>
            <td style={{ padding: '6px 4px' }}>
              <select value={newRow.stage} onChange={e => setNewRow(r => ({ ...r, stage: e.target.value }))}>
                {STAGES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </td>
            <td style={{ padding: '6px 4px' }}>
              <input type="time" value={newRow.start} onChange={e => setNewRow(r => ({ ...r, start: e.target.value }))} />
            </td>
            <td style={{ padding: '6px 4px' }}>
              <input type="time" value={newRow.end} onChange={e => setNewRow(r => ({ ...r, end: e.target.value }))} />
            </td>
            <td style={{ padding: '6px 4px' }}>
              <button onClick={addRow}
                style={{ background: '#3b82f6', color: '#fff', borderRadius: 4, padding: '3px 8px', fontSize: 12 }}>
                + Add
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      {/* Headliners */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: '#71717a', fontSize: 11, whiteSpace: 'nowrap' }}>Headliners (locked):</span>
        <input
          value={headliners.join(', ')}
          onChange={e => setHeadliners(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
          style={{ flex: 1, fontSize: 11 }}
          placeholder="Comma-separated artist names"
        />
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={loadDefaults}
          style={{ background: '#27272a', color: '#a1a1aa', border: '1px solid #3f3f46', borderRadius: 6, padding: '6px 12px' }}>
          Load Example
        </button>
        <button
          onClick={() => onOptimize(headliners)}
          disabled={isOptimizing || setlist.length < 2}
          style={{
            background: isOptimizing ? '#1d4ed8' : '#2563eb', color: '#fff',
            borderRadius: 6, padding: '6px 16px', fontWeight: 600,
            opacity: (isOptimizing || setlist.length < 2) ? 0.6 : 1,
          }}
        >
          {isOptimizing ? '⟳ Optimizing…' : '⚡ Optimize Schedule'}
        </button>

        {optimizeResult && (
          <span style={{ color: '#22c55e', fontSize: 12 }}>
            ✓ Risk {Math.round((optimizeResult.risk_before - optimizeResult.risk_after) / optimizeResult.risk_before * 100)}% reduced
          </span>
        )}
      </div>
    </div>
  )
}
