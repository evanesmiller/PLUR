import DeckGL from '@deck.gl/react'
import Map from 'react-map-gl/maplibre'
import { useMemo, useState } from 'react'
import { buildVenueLayers, buildSimLayers } from './layers.js'

// Pure dark canvas — no tile fetches, no attribution required
const DARK_STYLE = {
  version: 8,
  sources: {},
  layers: [{
    id: 'background',
    type: 'background',
    paint: { 'background-color': '#0a0b10' },
  }],
}

const INITIAL_VIEW = {
  longitude: -118.3396,
  latitude:   33.9525,
  zoom:        15.2,
  pitch:       45,
  bearing:      0,
}

export default function DeckMap({ venueGeoJSON, agents, zones, barriers, staff, hotspots, vis }) {
  const [tooltip, setTooltip] = useState(null)

  const venueLayers = useMemo(
    () => buildVenueLayers(venueGeoJSON),
    [venueGeoJSON],
  )

  const simLayers = useMemo(
    () => buildSimLayers({ agents, zones, barriers, staff, hotspots, vis }),
    [agents, zones, barriers, staff, hotspots, vis],
  )

  // venue layers below, sim layers on top
  const allLayers = [...venueLayers, ...simLayers]

  function handleHover(info) {
    setTooltip(info.object ? { x: info.x, y: info.y, object: info.object } : null)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 0 }}>
      <DeckGL
        initialViewState={INITIAL_VIEW}
        controller={true}
        layers={allLayers}
        onHover={handleHover}
      >
        <Map mapStyle={DARK_STYLE} />
      </DeckGL>

      {tooltip?.object && (
        <div style={{
          position: 'absolute',
          left: tooltip.x + 12,
          top:  tooltip.y + 12,
          background: 'rgba(18,18,22,0.94)',
          border: '1px solid #3f3f46',
          borderRadius: 8,
          padding: '8px 12px',
          pointerEvents: 'none',
          zIndex: 50,
          maxWidth: 240,
          backdropFilter: 'blur(8px)',
        }}>
          <TooltipContent obj={tooltip.object} />
        </div>
      )}
    </div>
  )
}

function TooltipContent({ obj }) {
  const p = obj.properties ?? {}

  // venue features
  if (p.type === 'stage') {
    return <>
      <div style={{ fontWeight: 700, color: '#f4f4f5', marginBottom: 3 }}>{p.name}</div>
      <div style={{ color: '#71717a', fontSize: 11 }}>Stage · cap {p.capacity_area_m2?.toLocaleString()} m²</div>
    </>
  }
  if (p.type === 'obstacle') {
    return <>
      <div style={{ fontWeight: 600, color: '#a1a1aa' }}>{p.name}</div>
      <div style={{ color: '#71717a', fontSize: 11 }}>{p.subtype}</div>
    </>
  }
  if (p.type === 'gate') {
    return <>
      <div style={{ fontWeight: 600, color: '#bae6fd' }}>{p.name}</div>
      <div style={{ color: '#71717a', fontSize: 11 }}>Cap {p.capacity_pph?.toLocaleString()} pph</div>
    </>
  }

  // sim features
  if (obj.level) {
    const c = { green:'#22c55e', yellow:'#eab308', orange:'#f97316', red:'#ef4444' }[obj.level]
    return <>
      <div style={{ fontWeight: 600, color: c }}>{obj.level.toUpperCase()} ZONE</div>
      <div style={{ color: '#a1a1aa', fontSize: 11 }}>Risk density region</div>
    </>
  }
  if (obj.segment) return <>
    <div style={{ fontWeight: 600, color: '#ffd200' }}>Recommended Barrier</div>
    <div style={{ color: '#a1a1aa', fontSize: 11, marginTop: 3 }}>{obj.reason}</div>
    <div style={{ color: '#60a5fa', marginTop: 4 }}>Est. reduction: {Math.round((obj.risk_reduction ?? 0) * 100)}%</div>
  </>
  if (obj.point) return <>
    <div style={{ fontWeight: 600, color: '#38bdf8' }}>Staff Position</div>
    <div style={{ color: '#a1a1aa', fontSize: 11, marginTop: 3 }}>{obj.reason}</div>
  </>
  if (obj.peak_density !== undefined && obj.lon !== undefined) return <>
    <div style={{ fontWeight: 600, color: '#ef4444' }}>Hotspot</div>
    <div style={{ color: '#a1a1aa', fontSize: 11 }}>Density: {obj.peak_density?.toFixed(1)} p/m²</div>
    <div style={{ color: '#a1a1aa', fontSize: 11 }}>Pressure: {obj.peak_pressure?.toFixed(2)}</div>
  </>

  return null
}
