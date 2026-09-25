const BASE = '/api'

async function get(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

async function put(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

async function del(path) {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

export const api = {
  // Projects
  getProjects: () => get('/projects'),
  getProject: id => get(`/projects/${id}`),
  createProject: data => post('/projects', data),
  updateProject: (id, data) => put(`/projects/${id}`, data),
  deleteProject: id => del(`/projects/${id}`),

  // Simulation
  simulateFestival: ({ projectId, setlist, sliders, barriers, densityRed, densityOrange, amenities }) =>
    post('/simulate_festival', {
      venue_id: 'hard_summer_2025',
      project_id: projectId || '',
      setlist,
      sliders,
      barriers,
      density_red: densityRed ?? 6.0,
      density_orange: densityOrange ?? 4.0,
      amenities: amenities ?? [],
    }),

  getSavedSim: id => get(`/projects/${id}/sim`),

  optimizeSchedule: (setlist, headliners, sliders, projectId) =>
    post('/optimize_schedule', {
      venue_id: 'hard_summer_2025',
      project_id: projectId || '',
      setlist,
      headliners,
      sliders,
    }),

  getDemandScores: (artists) => post('/demand/scores', { artists }),

  getSafetyBriefing: (setlist, sliders, peakDensity, hotspots, amenities, projectId) =>
    post('/safety_briefing', {
      venue_id: 'hard_summer_2025',
      project_id: projectId || '',
      setlist,
      sliders,
      peak_density: peakDensity,
      hotspots,
      amenities: amenities ?? [],
    }),
}
