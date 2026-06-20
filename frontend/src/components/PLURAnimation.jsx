import { useEffect, useRef } from 'react'

const SCATTER_FRAMES = 90   // ~1.5 s of random drift
const EASE_IN_FRAMES = 40   // ~0.67 s to ramp up pull
const LERP_MAX = 0.028      // slow, guaranteed-no-bounce convergence

export default function PLURAnimation({ onComplete }) {
  const canvasRef = useRef(null)
  const notifiedRef = useRef(false)
  // Stable ref so the effect never re-runs when the parent re-renders
  const onCompleteRef = useRef(onComplete)
  useEffect(() => { onCompleteRef.current = onComplete }, [onComplete])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    let width = window.innerWidth
    let height = window.innerHeight
    canvas.width = width
    canvas.height = height

    let frameId
    let particles = []
    let frame = 0

    async function init() {
      await document.fonts.ready
      frame = 0
      notifiedRef.current = false

      const targets = sampleTextPixels('PLUR', width, height)

      particles = targets.map(t => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 2.5,
        vy: (Math.random() - 0.5) * 2.5,
        tx: t.x,
        ty: t.y,
        r: Math.random() * 1.4 + 0.4,
      }))

      cancelAnimationFrame(frameId)
      frameId = requestAnimationFrame(draw)
    }

    function draw() {
      ctx.clearRect(0, 0, width, height)
      frame++

      const formPhase = Math.max(0, frame - SCATTER_FRAMES)
      const easeRatio = Math.min(1, formPhase / EASE_IN_FRAMES)
      // Lerp factor rises from 0 → LERP_MAX during ease-in, stays flat after.
      // Direct lerp (vx = dx * lerp, no accumulation) cannot overshoot — no bounce.
      const lerp = easeRatio * LERP_MAX

      let settled = 0

      for (const p of particles) {
        if (formPhase === 0) {
          // Scatter phase: gentle random impulses + damping → drifting cloud
          p.vx = (p.vx + (Math.random() - 0.5) * 0.5) * 0.975
          p.vy = (p.vy + (Math.random() - 0.5) * 0.5) * 0.975
          // Soft boundary — bounce back without energy gain
          if (p.x < 0)      { p.x = 0;     p.vx =  Math.abs(p.vx) * 0.4 }
          if (p.x > width)  { p.x = width;  p.vx = -Math.abs(p.vx) * 0.4 }
          if (p.y < 0)      { p.y = 0;     p.vy =  Math.abs(p.vy) * 0.4 }
          if (p.y > height) { p.y = height; p.vy = -Math.abs(p.vy) * 0.4 }
        } else {
          // Form phase: each frame velocity is recalculated from scratch (no accumulation).
          // This is equivalent to exponential smoothing and physically cannot overshoot.
          const dx = p.tx - p.x
          const dy = p.ty - p.y
          p.vx = dx * lerp
          p.vy = dy * lerp
          if (Math.abs(dx) < 2 && Math.abs(dy) < 2) settled++
        }

        p.x += p.vx
        p.y += p.vy

        // Blue-to-indigo gradient keyed to the particle's target x position
        const tpos = Math.max(0, Math.min(1, (p.tx - width * 0.12) / (width * 0.76)))
        const r = Math.round(59  + tpos * 99)
        const g = Math.round(130 - tpos * 90)
        const b = Math.round(246 - tpos * 30)
        // Particles are dim while scattered; brighten as they converge
        const alpha = formPhase === 0 ? 0.42 : Math.min(1, 0.42 + easeRatio * 0.58)

        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`
        ctx.fill()
      }

      if (formPhase > EASE_IN_FRAMES && settled > particles.length * 0.96 && !notifiedRef.current) {
        notifiedRef.current = true
        onCompleteRef.current?.()
      }

      frameId = requestAnimationFrame(draw)
    }

    init()

    const onResize = () => {
      width = canvas.width = window.innerWidth
      height = canvas.height = window.innerHeight
      notifiedRef.current = false
      init()
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(frameId)
      window.removeEventListener('resize', onResize)
    }
  }, []) // empty deps — runs once on mount; onComplete changes tracked via ref

  return (
    <canvas
      ref={canvasRef}
      style={{ display: 'block', width: '100%', height: '100%' }}
    />
  )
}

function sampleTextPixels(text, width, height) {
  const off = document.createElement('canvas')
  off.width = width
  off.height = height
  const ctx = off.getContext('2d')

  const fontSize = Math.min(Math.floor(width * 0.27), 260)
  ctx.font = `900 ${fontSize}px "Inter", "Arial Black", "Impact", sans-serif`
  ctx.fillStyle = '#ffffff'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, width / 2, height / 2)

  const { data } = ctx.getImageData(0, 0, width, height)
  const points = []
  const gap = 5

  for (let y = 0; y < height; y += gap) {
    for (let x = 0; x < width; x += gap) {
      if (data[(y * width + x) * 4 + 3] > 128) {
        points.push({ x, y })
      }
    }
  }

  return points
}
