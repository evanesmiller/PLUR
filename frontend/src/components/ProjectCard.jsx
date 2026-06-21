import { useState } from 'react'
import GeoJSONPreview from './GeoJSONPreview.jsx'

export default function ProjectCard({ project, onClick, onDelete }) {
  const [hovered, setHovered] = useState(false)
  const [confirming, setConfirming] = useState(false)

  function handleTrash(e) {
    e.stopPropagation()
    setConfirming(true)
  }

  function handleCancel(e) {
    e.stopPropagation()
    setConfirming(false)
  }

  function handleConfirm(e) {
    e.stopPropagation()
    setConfirming(false)
    onDelete?.(project.id)
  }

  return (
    <>
      <div
        onClick={onClick}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          position: 'relative',
          background: '#18181b',
          border: `1px solid ${hovered ? '#3b82f6' : '#27272a'}`,
          borderRadius: 12,
          overflow: 'hidden',
          cursor: 'pointer',
          transform: hovered ? 'translateY(-3px)' : 'none',
          transition: 'border-color 0.15s, transform 0.15s, box-shadow 0.15s',
          boxShadow: hovered ? '0 8px 32px rgba(59,130,246,0.15)' : 'none',
        }}
      >
        <button
          onClick={handleTrash}
          aria-label="Delete project"
          style={{
            position: 'absolute',
            top: 10,
            right: 10,
            zIndex: 2,
            background: 'rgba(24,24,27,0.88)',
            border: '1px solid #3f3f46',
            borderRadius: 6,
            width: 28,
            height: 28,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#ef4444',
            opacity: hovered ? 1 : 0,
            transition: 'opacity 0.15s, background 0.15s, border-color 0.15s',
            cursor: 'pointer',
            padding: 0,
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = '#2d1111'
            e.currentTarget.style.borderColor = '#991b1b'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'rgba(24,24,27,0.88)'
            e.currentTarget.style.borderColor = '#3f3f46'
          }}
        >
          <TrashIcon />
        </button>

        <div style={{ padding: '14px 18px 10px' }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: '#f4f4f5', marginBottom: 3 }}>
            {project.name}
          </div>
          <div style={{ fontSize: 12, color: '#71717a', display: 'flex', gap: 12 }}>
            <span>{project.artist_count} artist{project.artist_count !== 1 ? 's' : ''}</span>
            <span>{new Date(project.created_at).toLocaleDateString()}</span>
          </div>
        </div>
        <GeoJSONPreview geojson={project.thumbnail} width={320} height={190} />
      </div>

      {confirming && (
        <div
          onClick={e => e.stopPropagation()}
          style={{
            position: 'fixed', inset: 0, zIndex: 200,
            background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div style={{
            background: '#18181b',
            border: '1px solid #3f3f46',
            borderRadius: 14,
            padding: '28px 32px',
            maxWidth: 380,
            width: '90%',
          }}>
            <div style={{ fontWeight: 700, fontSize: 17, color: '#f4f4f5', marginBottom: 8 }}>
              Delete "{project.name}"?
            </div>
            <p style={{ color: '#a1a1aa', fontSize: 13, margin: '0 0 24px' }}>
              This action cannot be undone.
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                onClick={handleCancel}
                style={{
                  padding: '8px 18px',
                  background: '#27272a',
                  border: '1px solid #3f3f46',
                  borderRadius: 8,
                  color: '#a1a1aa',
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                style={{
                  padding: '8px 18px',
                  background: '#7f1d1d',
                  border: '1px solid #991b1b',
                  borderRadius: 8,
                  color: '#fca5a5',
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2" />
    </svg>
  )
}
