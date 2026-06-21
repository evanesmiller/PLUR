import { ScatterplotLayer, PathLayer, PolygonLayer, TextLayer } from '@deck.gl/layers'
import { HeatmapLayer } from '@deck.gl/aggregation-layers'

// ── venue colour palette ────────────────────────────────────────────────────

const STAGE_COLORS = {
  hard:        [220,  50,  50, 255],
  harder:      [255, 120,  30, 255],
  green:       [ 50, 200,  80, 255],
  purple:      [160,  80, 220, 255],
  pink:        [240,  80, 160, 255],
  beatbox:     [ 80, 200, 240, 255],
  locals_only: [255, 210,   0, 255],
}
const DEFAULT_STAGE_COLOR = [180, 180, 180, 255]

function stageColor(id) {
  return STAGE_COLORS[id] ?? DEFAULT_STAGE_COLOR
}

function obstacleColor(subtype) {
  switch (subtype) {
    case 'structure':  return [55, 55, 65, 220]   // SoFi — dark grey
    case 'terrain':    return [20, 35, 70, 210]   // lake — dark blue
    case 'barrier':    return [90, 30, 30, 200]   // barriers — dark red
    case 'stage_boh':  return [35, 35, 42, 210]   // back-of-house — near-black
    case 'bar':        return [60, 40, 20, 180]   // bars — dark amber
    case 'vendor':     return [40, 40, 25, 180]   // vendors — dark olive
    default:           return [50, 50, 55, 180]
  }
}

// ── venue layers ─────────────────────────────────────────────────────────────

export function buildVenueLayers(geojson) {
  if (!geojson?.features) return []

  const features = geojson.features
  const walkable  = features.filter(f => f.properties.type === 'walkable')
  const obstacles = features.filter(f => f.properties.type === 'obstacle' || f.properties.type === 'gate_area')
  const vip       = features.filter(f => f.properties.type === 'vip_area')
  const stages    = features.filter(f => f.properties.type === 'stage')
  const gates     = features.filter(f => f.properties.type === 'gate')
  const facilities= features.filter(f => f.properties.type === 'facility')

  return [
    // Festival grounds fill (bottom)
    new PolygonLayer({
      id: 'venue-walkable',
      data: walkable,
      getPolygon: f => f.geometry.coordinates[0],
      getFillColor: [18, 20, 26, 240],
      getLineColor: [60, 65, 80, 200],
      lineWidthMinPixels: 1.5,
      filled: true,
      stroked: true,
    }),

    // VIP areas
    new PolygonLayer({
      id: 'venue-vip',
      data: vip,
      getPolygon: f => f.geometry.coordinates[0],
      getFillColor: [70, 45, 110, 70],
      getLineColor: [140, 90, 200, 180],
      lineWidthMinPixels: 1,
      filled: true,
      stroked: true,
    }),

    // Obstacles (SoFi, lake, BOH, bars, barriers)
    new PolygonLayer({
      id: 'venue-obstacles',
      data: obstacles,
      getPolygon: f => f.geometry.coordinates[0],
      getFillColor: f => obstacleColor(f.properties.subtype),
      getLineColor: [70, 70, 80, 120],
      lineWidthMinPixels: 0.5,
      filled: true,
      stroked: true,
      pickable: true,
    }),

    // Facility markers (water, restroom)
    new ScatterplotLayer({
      id: 'venue-facilities',
      data: facilities,
      getPosition: f => f.geometry.coordinates,
      getRadius: 6,
      radiusUnits: 'meters',
      radiusMinPixels: 4,
      getFillColor: f => f.properties.facility_type === 'water'
        ? [30, 140, 220, 200]
        : [160, 160, 180, 200],
      getLineColor: [255, 255, 255, 120],
      stroked: true,
      lineWidthMinPixels: 1,
    }),

    // Gate markers
    new ScatterplotLayer({
      id: 'venue-gates',
      data: gates,
      getPosition: f => f.geometry.coordinates,
      getRadius: 10,
      radiusUnits: 'meters',
      radiusMinPixels: 6,
      getFillColor: [200, 230, 255, 220],
      getLineColor: [255, 255, 255, 255],
      stroked: true,
      lineWidthMinPixels: 2,
      pickable: true,
    }),

    // Stage glow (outer ring)
    new ScatterplotLayer({
      id: 'venue-stage-glow',
      data: stages,
      getPosition: f => f.geometry.coordinates,
      getRadius: 35,
      radiusUnits: 'meters',
      radiusMinPixels: 14,
      getFillColor: f => [...stageColor(f.properties.stage_id).slice(0, 3), 30],
      getLineColor: f => [...stageColor(f.properties.stage_id).slice(0, 3), 90],
      stroked: true,
      lineWidthMinPixels: 1,
    }),

    // Stage markers (inner dot)
    new ScatterplotLayer({
      id: 'venue-stages',
      data: stages,
      getPosition: f => f.geometry.coordinates,
      getRadius: 16,
      radiusUnits: 'meters',
      radiusMinPixels: 8,
      getFillColor: f => stageColor(f.properties.stage_id),
      getLineColor: [255, 255, 255, 200],
      stroked: true,
      lineWidthMinPixels: 2,
      pickable: true,
    }),

    // Stage name labels
    new TextLayer({
      id: 'venue-stage-labels',
      data: stages,
      getPosition: f => f.geometry.coordinates,
      getText: f => f.properties.name,
      getSize: 13,
      getColor: [255, 255, 255, 230],
      getPixelOffset: [0, -28],
      fontWeight: 700,
      fontFamily: 'Inter, system-ui, sans-serif',
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'center',
    }),

    // Gate labels
    new TextLayer({
      id: 'venue-gate-labels',
      data: gates,
      getPosition: f => f.geometry.coordinates,
      getText: f => f.properties.name,
      getSize: 10,
      getColor: [180, 210, 255, 200],
      getPixelOffset: [0, 20],
      fontFamily: 'Inter, system-ui, sans-serif',
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'center',
    }),
  ]
}

// ── simulation / risk layers ─────────────────────────────────────────────────

const ZONE_FILL = {
  green:  [34,  197, 94,  40],
  yellow: [234, 179,  8,  50],
  orange: [249, 115,  22, 60],
  red:    [239,  68,  68, 80],
}
const ZONE_LINE = {
  green:  [34,  197, 94,  160],
  yellow: [234, 179,  8,  180],
  orange: [249, 115,  22, 200],
  red:    [239,  68,  68, 230],
}

function speedColor(speed) {
  const t = Math.min(speed / 1.5, 1)
  return [Math.round(255 * (1 - t)), Math.round(50 * t), Math.round(255 * t), 210]
}

export function buildSimLayers({ agents, zones, barriers, staff, hotspots, vis }) {
  const layers = []

  if (vis.zones && zones.length > 0) {
    layers.push(new PolygonLayer({
      id: 'zones',
      data: zones,
      getPolygon: d => d.polygon,
      getFillColor: d => ZONE_FILL[d.level] ?? [100, 100, 100, 40],
      getLineColor: d => ZONE_LINE[d.level] ?? [100, 100, 100, 160],
      lineWidthMinPixels: 1.5,
      filled: true,
      stroked: true,
      pickable: true,
    }))
  }

  if (vis.heatmap && agents.length > 0) {
    layers.push(new HeatmapLayer({
      id: 'heatmap',
      data: agents,
      getPosition: d => [d[0], d[1]],
      radiusPixels: 35,
      intensity: 1.5,
      threshold: 0.05,
      colorRange: [
        [0,   200, 100, 150],
        [255, 235,   0, 190],
        [255, 140,   0, 220],
        [220,  40,  40, 255],
      ],
    }))
  }

  if (vis.agents && agents.length > 0) {
    layers.push(new ScatterplotLayer({
      id: 'agents',
      data: agents,
      getPosition: d => [d[0], d[1]],
      getRadius: 2,
      radiusUnits: 'meters',
      radiusMinPixels: 1.5,
      getFillColor: d => speedColor(Math.hypot(d[2] ?? 0, d[3] ?? 0)),
      pickable: false,
    }))
  }

  if (vis.barriers && barriers.length > 0) {
    layers.push(new PathLayer({
      id: 'barriers',
      data: barriers,
      getPath: d => d.segment,
      getColor: [255, 210, 0, 230],
      getWidth: 4,
      widthUnits: 'meters',
      widthMinPixels: 3,
      pickable: true,
    }))
  }

  if (vis.staff && staff.length > 0) {
    layers.push(new ScatterplotLayer({
      id: 'staff',
      data: staff,
      getPosition: d => d.point,
      getRadius: 8,
      radiusUnits: 'meters',
      radiusMinPixels: 6,
      getFillColor: [56, 189, 248, 220],
      getLineColor: [255, 255, 255, 200],
      stroked: true,
      lineWidthMinPixels: 2,
      pickable: true,
    }))
  }

  if (vis.hotspots && hotspots.length > 0) {
    layers.push(new ScatterplotLayer({
      id: 'hotspots',
      data: hotspots,
      getPosition: d => [d.lon, d.lat],
      getRadius: 15,
      radiusUnits: 'meters',
      radiusMinPixels: 8,
      getFillColor: [0, 0, 0, 0],
      getLineColor: [255, 40, 40, 255],
      stroked: true,
      lineWidthMinPixels: 2.5,
      pickable: true,
    }))
  }

  return layers
}

// kept for backwards-compat with any import that uses buildLayers
export { buildSimLayers as buildLayers }
