const LAYER_BUTTONS = [
  { key: 'heatmap', label: 'Heat', icon: '🌡' },
  { key: 'agents',  label: 'Agents', icon: '·' },
  { key: 'zones',   label: 'Zones', icon: '⬡' },
  { key: 'barriers',label: 'Barriers', icon: '—' },
  { key: 'staff',   label: 'Staff', icon: '⊕' },
  { key: 'hotspots',label: 'Hotspots', icon: '◎' },
]

const RISK_PILL = {
  none:   { label: 'No Data',  bg: '#27272a', color: '#71717a' },
  low:    { label: 'Low Risk', bg: '#14532d', color: '#22c55e' },
  medium: { label: 'Moderate', bg: '#713f12', color: '#eab308' },
  high:   { label: 'High Risk',bg: '#7f1d1d', color: '#ef4444' },
}

function riskLevel(peakDensity) {
  if (peakDensity >= 6) return 'high'
  if (peakDensity >= 4) return 'medium'
  if (peakDensity >= 1) return 'low'
  return 'none'
}

export default function TopBar({ vis, onToggleLayer, onRun, isRunning, peakDensity, frameCount }) {
  const lvl = riskLevel(peakDensity)
  const pill = RISK_PILL[lvl]

  return (
    <div style={{
      position: 'absolute', top: 0, left: 0, right: 0, zIndex: 20,
      height: 52,
      background: 'rgba(24,24,27,0.88)',
      backdropFilter: 'blur(12px)',
      borderBottom: '1px solid #3f3f46',
      display: 'flex', alignItems: 'center', gap: 0,
      padding: '0 16px',
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', flexDirection: 'column', marginRight: 20 }}>
        <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: 3, color: '#60a5fa' }}>
          PLUR
        </span>
        <span style={{ fontSize: 10, color: '#71717a', letterSpacing: 1, marginTop: -2 }}>
          CROWD SAFETY
        </span>
      </div>

      <div style={{ width: 1, height: 32, background: '#3f3f46', marginRight: 16 }} />

      {/* Venue + risk */}
      <div style={{ display: 'flex', flexDirection: 'column', marginRight: 20, minWidth: 160 }}>
        <span style={{ fontWeight: 600, color: '#f4f4f5', fontSize: 13 }}>
          HARD Summer 2025
        </span>
        <span style={{ color: '#71717a', fontSize: 11, marginTop: 1 }}>
          Hollywood Park · {frameCount > 0 ? `${frameCount} frames` : 'No sim loaded'}
        </span>
      </div>

      {/* Risk pill */}
      <div style={{
        background: pill.bg, color: pill.color,
        borderRadius: 20, padding: '3px 10px',
        fontWeight: 600, fontSize: 11, letterSpacing: 0.5,
        marginRight: 20,
        border: `1px solid ${pill.color}44`,
      }}>
        {pill.label}
        {peakDensity > 0 && (
          <span style={{ marginLeft: 6, opacity: 0.8 }}>
            {peakDensity.toFixed(1)} p/m²
          </span>
        )}
      </div>

      <div style={{ flex: 1 }} />

      {/* Layer toggles */}
      <div style={{ display: 'flex', gap: 4, marginRight: 12 }}>
        {LAYER_BUTTONS.map(({ key, label, icon }) => (
          <button
            key={key}
            onClick={() => onToggleLayer(key)}
            title={label}
            style={{
              background: vis[key] ? 'rgba(59,130,246,0.2)' : 'transparent',
              color: vis[key] ? '#60a5fa' : '#71717a',
              border: `1px solid ${vis[key] ? '#3b82f6' : '#3f3f46'}`,
              borderRadius: 6,
              padding: '4px 10px',
              fontSize: 11,
              fontWeight: vis[key] ? 600 : 400,
              transition: 'all 0.15s',
            }}
          >
            {icon} {label}
          </button>
        ))}
      </div>

      {/* Run button */}
      <button
        onClick={onRun}
        disabled={isRunning}
        style={{
          background: isRunning ? '#1d4ed8' : '#3b82f6',
          color: '#fff',
          borderRadius: 8,
          padding: '7px 18px',
          fontWeight: 600,
          fontSize: 13,
          opacity: isRunning ? 0.7 : 1,
          transition: 'all 0.15s',
          minWidth: 100,
        }}
      >
        {isRunning ? '⟳ Running…' : '▶ Run Sim'}
      </button>
    </div>
  )
}
