const STAGE_COLORS = {
  hard: '#ef4444',
  harder: '#f97316',
  green: '#22c55e',
  purple: '#a855f7',
  pink: '#ec4899',
  beatbox: '#22d3ee',
  locals_only: '#fbbf24',
}

export default function GeoJSONPreview({ geojson, width = 280, height = 180 }) {
  if (!geojson) {
    return <div style={{ width, height, background: '#111113', borderRadius: 8 }} />
  }

  // Accept either a full FeatureCollection or a single walkable Feature
  let features = []
  if (geojson.type === 'FeatureCollection') {
    features = geojson.features ?? []
  } else if (geojson.type === 'Feature') {
    features = [geojson]
  }

  const walkable = features.find(f => f?.properties?.type === 'walkable')
  if (!walkable || walkable.geometry?.type !== 'Polygon') {
    return <div style={{ width, height, background: '#111113', borderRadius: 8 }} />
  }

  const coords = walkable.geometry.coordinates[0]
  const stages = features.filter(f => f?.properties?.type === 'stage')
  const gates = features.filter(f => f?.properties?.type === 'gate')

  const pad = 14
  const lons = coords.map(c => c[0])
  const lats = coords.map(c => c[1])
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const lonRange = maxLon - minLon || 1e-5
  const latRange = maxLat - minLat || 1e-5

  const scaleX = (width - pad * 2) / lonRange
  const scaleY = (height - pad * 2) / latRange
  const scale = Math.min(scaleX, scaleY)

  const ox = pad + ((width - pad * 2) - lonRange * scale) / 2
  const oy = pad + ((height - pad * 2) - latRange * scale) / 2

  function toSVG([lon, lat]) {
    return [
      (ox + (lon - minLon) * scale).toFixed(1),
      (oy + (maxLat - lat) * scale).toFixed(1),
    ]
  }

  const d =
    coords
      .map((c, i) => {
        const [x, y] = toSVG(c)
        return `${i === 0 ? 'M' : 'L'}${x},${y}`
      })
      .join(' ') + ' Z'

  return (
    <svg width={width} height={height} style={{ display: 'block', borderRadius: 8 }}>
      <rect width={width} height={height} fill="#0d0d0f" rx="8" />
      <path d={d} fill="#111d33" stroke="#1d4ed8" strokeWidth="1.5" strokeOpacity="0.7" />
      {gates.map((g, i) => {
        const [x, y] = toSVG(g.geometry.coordinates)
        return <circle key={`g${i}`} cx={x} cy={y} r="5" fill="#bae6fd" opacity="0.8" />
      })}
      {stages.map((s, i) => {
        const [x, y] = toSVG(s.geometry.coordinates)
        const color = STAGE_COLORS[s.properties.stage_id] ?? '#888'
        return (
          <g key={`s${i}`}>
            <circle cx={x} cy={y} r="7" fill={color} opacity="0.25" />
            <circle cx={x} cy={y} r="3.5" fill={color} />
          </g>
        )
      })}
    </svg>
  )
}
