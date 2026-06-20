export default function ClaudePanel({ briefing, rationale, isLoading }) {
  return (
    <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {isLoading && (
        <div style={{ color: '#60a5fa', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</span>
          Generating AI safety briefing…
        </div>
      )}

      {rationale && (
        <Section title="Schedule Rationale" icon="⚡" color="#60a5fa">
          {rationale}
        </Section>
      )}

      {briefing ? (
        <Section title="Safety Briefing" icon="🛡" color="#22c55e">
          {briefing}
        </Section>
      ) : (
        !isLoading && (
          <div style={{
            textAlign: 'center', padding: '24px 0', color: '#3f3f46',
            border: '1px dashed #27272a', borderRadius: 8,
          }}>
            <div style={{ fontSize: 24, marginBottom: 8 }}>🤖</div>
            <div style={{ color: '#71717a' }}>
              Run a simulation or optimize the schedule to generate an AI briefing.
            </div>
          </div>
        )
      )}

      <div style={{ color: '#3f3f46', fontSize: 10, borderTop: '1px solid #27272a', paddingTop: 8 }}>
        Powered by Claude claude-sonnet-4-6 · PLUR is a planning and decision-support prototype, not a certified life-safety system.
      </div>
    </div>
  )
}

function Section({ title, icon, color, children }) {
  return (
    <div style={{
      background: '#18181b', border: '1px solid #27272a', borderRadius: 8,
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '8px 14px',
        background: '#27272a',
        color,
        fontWeight: 600,
        fontSize: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}>
        {icon} {title}
      </div>
      <div style={{
        padding: '12px 14px',
        color: '#a1a1aa',
        fontSize: 12,
        lineHeight: 1.6,
        whiteSpace: 'pre-wrap',
        maxHeight: 180,
        overflowY: 'auto',
      }}>
        {children}
      </div>
    </div>
  )
}
