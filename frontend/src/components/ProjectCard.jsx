import { useState } from 'react'
import GeoJSONPreview from './GeoJSONPreview.jsx'

export default function ProjectCard({ project, onClick }) {
  const [hovered, setHovered] = useState(false)

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
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
  )
}
