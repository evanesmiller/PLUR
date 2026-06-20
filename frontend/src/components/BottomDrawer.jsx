import { useState } from 'react'
import TimelineScrubber from './TimelineScrubber.jsx'
import ScheduleEditor from './ScheduleEditor.jsx'
import ClaudePanel from './ClaudePanel.jsx'

const TABS = [
  { key: 'timeline', label: '⏱ Timeline' },
  { key: 'schedule', label: '🎵 Schedule' },
  { key: 'briefing', label: '🤖 AI Briefing' },
]

const DRAWER_COLLAPSED = 28
const DRAWER_EXPANDED  = 340

export default function BottomDrawer({
  frames, frameIdx, setFrameIdx, isPlaying, setIsPlaying,
  peakDensity, peakPressure, hotspots,
  setlist, onSetlistChange, onOptimize, isOptimizing, optimizeResult,
  briefing, rationale, isClaudeLoading,
}) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState('timeline')

  const height = open ? DRAWER_EXPANDED : DRAWER_COLLAPSED

  return (
    <div style={{
      position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 20,
      height,
      background: 'rgba(24,24,27,0.92)',
      backdropFilter: 'blur(12px)',
      borderTop: '1px solid #3f3f46',
      transition: 'height 0.25s cubic-bezier(0.4,0,0.2,1)',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Handle + tab bar */}
      <div style={{
        height: DRAWER_COLLAPSED,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        cursor: 'pointer',
        gap: 12,
      }}
        onClick={() => setOpen(o => !o)}
      >
        {/* Grab pill */}
        <div style={{
          width: 40, height: 4, borderRadius: 2,
          background: open ? '#60a5fa' : '#3f3f46',
          transition: 'background 0.2s',
          flexShrink: 0,
        }} />

        {open && TABS.map(t => (
          <button
            key={t.key}
            onClick={e => { e.stopPropagation(); setTab(t.key) }}
            style={{
              background: tab === t.key ? 'rgba(59,130,246,0.15)' : 'transparent',
              color: tab === t.key ? '#60a5fa' : '#71717a',
              border: `1px solid ${tab === t.key ? '#3b82f6' : 'transparent'}`,
              borderRadius: 6,
              padding: '3px 12px',
              fontSize: 12,
              fontWeight: tab === t.key ? 600 : 400,
            }}
          >
            {t.label}
          </button>
        ))}

        {!open && frames.length > 0 && (
          <span style={{ color: '#a1a1aa', fontSize: 11 }}>
            {frames.length} frames · peak {peakDensity.toFixed(1)} p/m² · {hotspots.length} hotspots
          </span>
        )}

        <div style={{ flex: 1 }} />
        <span style={{ color: '#3f3f46', fontSize: 16, userSelect: 'none' }}>
          {open ? '▾' : '▴'}
        </span>
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
        {tab === 'timeline' && (
          <TimelineScrubber
            frames={frames}
            frameIdx={frameIdx}
            setFrameIdx={setFrameIdx}
            isPlaying={isPlaying}
            setIsPlaying={setIsPlaying}
            peakDensity={peakDensity}
            peakPressure={peakPressure}
            hotspots={hotspots}
          />
        )}
        {tab === 'schedule' && (
          <ScheduleEditor
            setlist={setlist}
            onChange={onSetlistChange}
            onOptimize={onOptimize}
            isOptimizing={isOptimizing}
            optimizeResult={optimizeResult}
          />
        )}
        {tab === 'briefing' && (
          <ClaudePanel
            briefing={briefing}
            rationale={rationale}
            isLoading={isClaudeLoading}
          />
        )}
      </div>
    </div>
  )
}
