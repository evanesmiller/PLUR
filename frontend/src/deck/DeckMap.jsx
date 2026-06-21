import DeckGL from '@deck.gl/react'
import Map from 'react-map-gl/maplibre'
import { useMemo, useState, useCallback, useRef } from 'react'
import { ScatterplotLayer, PolygonLayer } from '@deck.gl/layers'
import { buildVenueLayers, buildSimLayers, buildAmenityLayers } from './layers.js'

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

export default function DeckMap({
  venueGeoJSON, agents, barriers, hotspots, vis,
  addMode, onMapClick, selectedBarrierId, onBarrierClick,
  onBarrierUpdate,
  amenities, selectedAmenityId, onAmenityClick, onAmenityUpdate,
}) {
  const [tooltip, setTooltip] = useState(null)
  const dragRef = useRef(null)

  const venueLayers = useMemo(
    () => buildVenueLayers(venueGeoJSON, amenities),
    [venueGeoJSON, amenities],
  )

  const simLayers = useMemo(
    () => buildSimLayers({ agents, barriers, hotspots, vis }),
    [agents, barriers, hotspots, vis],
  )

  const amenityLayers = useMemo(
    () => buildAmenityLayers(amenities ?? [], selectedAmenityId),
    [amenities, selectedAmenityId],
  )

  const handleLayers = useMemo(() => {
    if (!selectedBarrierId) return []
    const sel = barriers.find(b => b.barrierId === selectedBarrierId)
    if (!sel) return []

    const corners = sel.polygon.slice(0, 4).map((c, i) => ({
      position: c,
      cornerIdx: i,
      barrierId: sel.barrierId,
    }))

    const top0 = sel.polygon[3]
    const top1 = sel.polygon[2]
    const rotateHandle = {
      position: [(top0[0] + top1[0]) / 2, (top0[1] + top1[1]) / 2],
      barrierId: sel.barrierId,
      isRotateHandle: true,
    }

    return [
      new PolygonLayer({
        id: 'selected-barrier-outline',
        data: [sel],
        getPolygon: d => d.polygon,
        getFillColor: [255, 210, 0, 30],
        getLineColor: [255, 255, 255, 255],
        lineWidthMinPixels: 2,
        filled: true,
        stroked: true,
      }),
      new ScatterplotLayer({
        id: 'barrier-handles',
        data: corners,
        getPosition: d => d.position,
        getRadius: 5,
        radiusUnits: 'meters',
        radiusMinPixels: 6,
        getFillColor: [255, 255, 255, 240],
        getLineColor: [255, 210, 0, 255],
        stroked: true,
        lineWidthMinPixels: 2,
        pickable: true,
      }),
      new ScatterplotLayer({
        id: 'barrier-rotate-handle',
        data: [rotateHandle],
        getPosition: d => d.position,
        getRadius: 5,
        radiusUnits: 'meters',
        radiusMinPixels: 6,
        getFillColor: [120, 220, 255, 240],
        getLineColor: [0, 180, 255, 255],
        stroked: true,
        lineWidthMinPixels: 2,
        pickable: true,
      }),
    ]
  }, [selectedBarrierId, barriers])

  const allLayers = [...venueLayers, ...simLayers, ...amenityLayers, ...handleLayers]

  function handleHover(info) {
    if (dragRef.current) return
    setTooltip(info.object ? { x: info.x, y: info.y, object: info.object } : null)
  }

  function handleClick(info) {
    if (dragRef.current) return

    // Amenity click
    if (info.object?.amenityId) {
      onAmenityClick?.(info.object.amenityId)
      onBarrierClick?.(null)
      return
    }

    // Barrier click
    if (info.object?.barrierId && info.object.cornerIdx === undefined && !info.object.isRotateHandle) {
      onBarrierClick?.(info.object.barrierId)
      onAmenityClick?.(null)
      return
    }

    if (addMode === 'barrier' && info.coordinate) {
      onMapClick?.(info.coordinate)
      return
    }

    // Click on empty space — deselect everything
    if (!info.object?.barrierId && !info.object?.isRotateHandle && !info.object?.amenityId) {
      onBarrierClick?.(null)
      onAmenityClick?.(null)
    }
  }

  const onDragStart = useCallback((info) => {
    if (!info.object) return

    // Amenity move drag
    if (info.object.amenityId) {
      dragRef.current = { type: 'move_amenity', amenityId: info.object.amenityId, startCoord: info.coordinate }
      return true
    }

    if (info.object.isRotateHandle) {
      const sel = barriers.find(b => b.barrierId === info.object.barrierId)
      if (sel) {
        dragRef.current = { type: 'rotate', barrierId: info.object.barrierId, cx: sel.cx, cy: sel.cy }
        return true
      }
    }
    if (info.object.cornerIdx !== undefined) {
      dragRef.current = { type: 'resize', barrierId: info.object.barrierId, cornerIdx: info.object.cornerIdx }
      return true
    }
    if (info.object.barrierId) {
      dragRef.current = { type: 'move', barrierId: info.object.barrierId, startCoord: info.coordinate }
      return true
    }
  }, [barriers, amenities])

  const onDrag = useCallback((info) => {
    if (!dragRef.current || !info.coordinate) return
    const d = dragRef.current

    if (d.type === 'move_amenity') {
      const dx = info.coordinate[0] - d.startCoord[0]
      const dy = info.coordinate[1] - d.startCoord[1]
      const am = amenities?.find(a => a.id === d.amenityId)
      if (am) onAmenityUpdate?.(d.amenityId, { lon: am.lon + dx, lat: am.lat + dy })
      d.startCoord = info.coordinate
      return
    }

    if (!onBarrierUpdate) return
    const sel = barriers.find(b => b.barrierId === d.barrierId)
    if (!sel) return

    if (d.type === 'move') {
      const dx = info.coordinate[0] - d.startCoord[0]
      const dy = info.coordinate[1] - d.startCoord[1]
      onBarrierUpdate(d.barrierId, { cx: sel.cx + dx, cy: sel.cy + dy })
      d.startCoord = info.coordinate

    } else if (d.type === 'resize') {
      const ci = d.cornerIdx
      const cos = Math.cos(-sel.angle)
      const sin = Math.sin(-sel.angle)
      const dx = info.coordinate[0] - sel.cx
      const dy = info.coordinate[1] - sel.cy
      const lx = dx * cos - dy * sin
      const ly = dx * sin + dy * cos
      const oppIdx = (ci + 2) % 4
      const oppLocal = [
        [-sel.hw, -sel.hh],
        [ sel.hw, -sel.hh],
        [ sel.hw,  sel.hh],
        [-sel.hw,  sel.hh],
      ][oppIdx]
      const newCx = sel.cx + ((lx + oppLocal[0]) / 2) * Math.cos(sel.angle) - ((ly + oppLocal[1]) / 2) * Math.sin(sel.angle)
      const newCy = sel.cy + ((lx + oppLocal[0]) / 2) * Math.sin(sel.angle) + ((ly + oppLocal[1]) / 2) * Math.cos(sel.angle)
      const newHw = Math.abs(lx - oppLocal[0]) / 2
      const newHh = Math.abs(ly - oppLocal[1]) / 2
      if (newHw > 0.00002 && newHh > 0.00002) {
        onBarrierUpdate(d.barrierId, { cx: newCx, cy: newCy, hw: newHw, hh: newHh })
      }

    } else if (d.type === 'rotate') {
      const angle = Math.atan2(info.coordinate[1] - d.cy, info.coordinate[0] - d.cx) - Math.PI / 2
      onBarrierUpdate(d.barrierId, { angle })
    }
  }, [barriers, amenities, onBarrierUpdate, onAmenityUpdate])

  const onDragEnd = useCallback(() => {
    dragRef.current = null
  }, [])

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 0,
      cursor: addMode === 'barrier' ? 'crosshair' : 'grab',
    }}>
      <DeckGL
        initialViewState={INITIAL_VIEW}
        controller={{ dragPan: !dragRef.current, dragRotate: !dragRef.current }}
        layers={allLayers}
        onHover={handleHover}
        onClick={handleClick}
        onDragStart={onDragStart}
        onDrag={onDrag}
        onDragEnd={onDragEnd}
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

  // Dynamic amenity data objects (have amenityId marker)
  if (obj.amenityId) {
    const COLOR = { water: '#60a5fa', restroom: '#a1a1aa', bar: '#d97706' }
    const LABEL = { water: 'Water Station', restroom: 'Restrooms', bar: 'Bar' }
    return <>
      <div style={{ fontWeight: 600, color: COLOR[obj.facility_type] ?? '#a1a1aa' }}>{obj.name}</div>
      <div style={{ color: '#71717a', fontSize: 11 }}>{LABEL[obj.facility_type] ?? obj.facility_type}</div>
      <div style={{ color: '#52525b', fontSize: 10 }}>Click to select · drag to move</div>
    </>
  }

  if (p.type === 'obstacle') {
    return <>
      <div style={{ fontWeight: 600, color: '#a1a1aa' }}>{p.name}</div>
      <div style={{ color: '#71717a', fontSize: 11 }}>{p.subtype}</div>
    </>
  }
  if (p.type === 'vip_area') {
    return <>
      <div style={{ fontWeight: 600, color: '#c4a5f7' }}>{p.name}</div>
      <div style={{ color: '#71717a', fontSize: 11 }}>VIP only — restricted access</div>
    </>
  }
  if (p.type === 'facility') {
    const color = p.facility_type === 'water' ? '#60a5fa' : '#a1a1aa'
    const label = p.facility_type === 'water' ? 'Water Station' : 'Restrooms'
    return <>
      <div style={{ fontWeight: 600, color }}>{p.name}</div>
      <div style={{ color: '#71717a', fontSize: 11 }}>{label}</div>
    </>
  }
  if (p.type === 'gate') {
    return <>
      <div style={{ fontWeight: 600, color: '#bae6fd' }}>{p.name}</div>
      <div style={{ color: '#71717a', fontSize: 11 }}>Cap {p.capacity_pph?.toLocaleString()} pph</div>
    </>
  }

  if (obj.isRotateHandle) return <>
    <div style={{ fontWeight: 600, color: '#78dcff' }}>Rotate</div>
    <div style={{ color: '#a1a1aa', fontSize: 11 }}>Drag to rotate barrier</div>
  </>
  if (obj.barrierId && obj.cornerIdx === undefined) return <>
    <div style={{ fontWeight: 600, color: '#ffd200' }}>Barrier</div>
    <div style={{ color: '#a1a1aa', fontSize: 11 }}>Click to select · drag to move</div>
  </>
  if (obj.cornerIdx !== undefined) return <>
    <div style={{ fontWeight: 600, color: '#fff' }}>Resize</div>
    <div style={{ color: '#a1a1aa', fontSize: 11 }}>Drag to resize barrier</div>
  </>
  if (obj.peak_density !== undefined && obj.lon !== undefined) return <>
    <div style={{ fontWeight: 600, color: '#ef4444' }}>Hotspot</div>
    <div style={{ color: '#a1a1aa', fontSize: 11 }}>Density: {obj.peak_density?.toFixed(1)} p/m²</div>
    <div style={{ color: '#a1a1aa', fontSize: 11 }}>Pressure: {obj.peak_pressure?.toFixed(2)}</div>
  </>

  return null
}
