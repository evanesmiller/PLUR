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

  // Venues
  getVenue: (id = 'hard_summer_2025') => get(`/venues/${id}`),

  // Simulation
  simulateFestival: ({ setlist, sliders, barriers }) =>
    post('/simulate_festival', {
      venue_id: 'hard_summer_2025',
      setlist,
      sliders,
      barriers,
    }),

  optimizeSchedule: (setlist, headliners, sliders) =>
    post('/optimize_schedule', {
      venue_id: 'hard_summer_2025',
      setlist,
      headliners,
      sliders,
    }),
}
