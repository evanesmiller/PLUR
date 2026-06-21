import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import PLURAnimation from '../components/PLURAnimation.jsx'
import ProjectCard from '../components/ProjectCard.jsx'
import { api } from '../api/client.js'

export default function Landing() {
  const alreadyPlayed = sessionStorage.getItem('plurAnimPlayed') === '1'
  const [animDone, setAnimDone] = useState(alreadyPlayed)
  const [projects, setProjects] = useState([])
  const projectsRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    api.getProjects().then(setProjects).catch(() => {})
  }, [])

  async function handleDelete(id) {
    try {
      await api.deleteProject(id)
      setProjects(prev => prev.filter(p => p.id !== id))
    } catch {}
  }

  function scrollToProjects() {
    window.scrollTo({ top: window.innerHeight, behavior: 'smooth' })
  }

  return (
    <div style={{ background: '#09090b', minHeight: '100vh', color: '#f4f4f5', fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* ── Hero (always shown, animation only on first visit) ──── */}
      <section style={{ height: '100vh', position: 'relative', overflow: 'hidden' }}>
        <PLURAnimation
          skipIntro={alreadyPlayed}
          onComplete={() => {
            sessionStorage.setItem('plurAnimPlayed', '1')
            setAnimDone(true)
          }}
        />

        <div style={{
          position: 'absolute', bottom: 112, left: 0, right: 0, textAlign: 'center',
          opacity: animDone ? 1 : 0, transition: 'opacity 1.2s ease',
          pointerEvents: 'none',
        }}>
          <p style={{
            color: '#52525b', fontSize: 13, letterSpacing: '0.18em',
            textTransform: 'uppercase', margin: 0,
          }}>
            Predictive Large-scale User Routing
          </p>
        </div>

        <button
          onClick={scrollToProjects}
          aria-label="Scroll to projects"
          style={{
            position: 'absolute', bottom: 44, left: '50%', transform: 'translateX(-50%)',
            background: 'none', border: 'none', cursor: 'pointer', padding: 12,
            color: '#3f3f46', opacity: animDone ? 1 : 0,
            transition: 'opacity 1.2s ease 0.4s, color 0.15s',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = '#a1a1aa')}
          onMouseLeave={e => (e.currentTarget.style.color = '#3f3f46')}
        >
          <ChevronDown />
        </button>
      </section>

      {/* ── Projects ─────────────────────────────────────────────── */}
      <section
        ref={projectsRef}
        style={{ maxWidth: 1080, margin: '0 auto', padding: '96px 32px 160px', minHeight: '100vh' }}
      >
        <h2 style={{ fontSize: 26, fontWeight: 700, margin: '0 0 6px' }}>Projects</h2>
        <p style={{ color: '#71717a', fontSize: 14, margin: '0 0 40px' }}>
          Select a festival to view its simulation, or start a new one.
        </p>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
          gap: 24,
        }}>
          {projects.map(p => (
            <ProjectCard
              key={p.id}
              project={p}
              onClick={() => navigate(`/projects/${p.id}`)}
              onDelete={handleDelete}
            />
          ))}

          <NewProjectCard onClick={() => navigate('/projects/new')} />
        </div>
      </section>
    </div>
  )
}

function NewProjectCard({ onClick }) {
  const [hovered, setHovered] = useState(false)
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: hovered ? '#111d33' : '#18181b',
        border: `2px dashed ${hovered ? '#3b82f6' : '#3f3f46'}`,
        borderRadius: 12,
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 240,
        gap: 12,
        transition: 'border-color 0.15s, background 0.15s',
      }}
    >
      <div style={{
        width: 48, height: 48, borderRadius: '50%',
        background: hovered ? '#1e3a5f' : '#27272a',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 28, color: hovered ? '#60a5fa' : '#52525b',
        transition: 'all 0.15s',
      }}>
        +
      </div>
      <span style={{ color: hovered ? '#93c5fd' : '#71717a', fontSize: 14, fontWeight: 600, transition: 'color 0.15s' }}>
        New Project
      </span>
    </div>
  )
}

function ChevronDown() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}
