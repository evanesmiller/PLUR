import { useEffect, useRef } from 'react'

const SCATTER_FRAMES  = 90   // ~1.5 s random drift
const EASE_IN_FRAMES  = 40   // ~0.67 s ramp-up
const LERP_MAX        = 0.028
const WAVE_FADE_IN    = 90   // frames to blend from static → wave after settling

// Blue #3b82f6  →  Purple #a855f7
const BLUE   = [59,  130, 246]
const PURPLE = [168,  85, 247]

export default function PLURAnimation({ onComplete }) {
  const canvasRef      = useRef(null)
  const notifiedRef    = useRef(false)
  const onCompleteRef  = useRef(onComplete)
  useEffect(() => { onCompleteRef.current = onComplete }, [onComplete])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    let width  = window.innerWidth
    let height = window.innerHeight
    canvas.width  = width
    canvas.height = height

    let frameId
    let particles   = []
    let frame       = 0
    let settledAt   = -1   // frame index when 96 % settled; -1 = not yet

    async function init() {
      await document.fonts.ready
      frame     = 0
      settledAt = -1
      notifiedRef.current = false

      const targets = sampleTextPixels('PLUR', width, height)

      particles = targets.map(t => ({
        x:  Math.random() * width,
        y:  Math.random() * height,
        vx: (Math.random() - 0.5) * 2.5,
        vy: (Math.random() - 0.5) * 2.5,
        tx: t.x,
        ty: t.y,
        r:  Math.random() * 1.4 + 0.4,
      }))

      cancelAnimationFrame(frameId)
      frameId = requestAnimationFrame(draw)
    }

    function draw() {
      ctx.clearRect(0, 0, width, height)
      frame++

      const formPhase = Math.max(0, frame - SCATTER_FRAMES)
      const easeRatio = Math.min(1, formPhase / EASE_IN_FRAMES)
      const lerp      = easeRatio * LERP_MAX

      // How many frames since the word fully settled
      const waveTick  = settledAt >= 0 ? frame - settledAt : -1
      const waveAmt   = waveTick < 0 ? 0 : Math.min(1, waveTick / WAVE_FADE_IN)

      let settled = 0

      for (const p of particles) {
        // ── Movement ──────────────────────────────────────────────
        if (formPhase === 0) {
          p.vx = (p.vx + (Math.random() - 0.5) * 0.5) * 0.975
          p.vy = (p.vy + (Math.random() - 0.5) * 0.5) * 0.975
          if (p.x < 0)      { p.x = 0;     p.vx =  Math.abs(p.vx) * 0.4 }
          if (p.x > width)  { p.x = width;  p.vx = -Math.abs(p.vx) * 0.4 }
          if (p.y < 0)      { p.y = 0;     p.vy =  Math.abs(p.vy) * 0.4 }
          if (p.y > height) { p.y = height; p.vy = -Math.abs(p.vy) * 0.4 }
        } else {
          const dx = p.tx - p.x
          const dy = p.ty - p.y
          p.vx = dx * lerp
          p.vy = dy * lerp
          if (Math.abs(dx) < 2 && Math.abs(dy) < 2) settled++
        }
        p.x += p.vx
        p.y += p.vy

        // ── Color ─────────────────────────────────────────────────
        // Normalised horizontal position of this particle's target (0 = left, 1 = right)
        const tpos = Math.max(0, Math.min(1, (p.tx - width * 0.12) / (width * 0.76)))

        let cr, cg, cb, alpha

        if (waveAmt === 0) {
          // Static blue-to-indigo gradient during scatter + form phases
          cr = Math.round(BLUE[0] + tpos * (PURPLE[0] - BLUE[0]) * 0.7)
          cg = Math.round(BLUE[1] + tpos * (PURPLE[1] - BLUE[1]) * 0.7)
          cb = Math.round(BLUE[2] + tpos * (PURPLE[2] - BLUE[2]) * 0.7)
          alpha = formPhase === 0 ? 0.42 : Math.min(1, 0.42 + easeRatio * 0.58)
        } else {
          // Travelling sine wave: ~2 full cycles across the word, moving left → right
          const wavePhase = tpos * Math.PI * 4 - waveTick * 0.04
          const w = Math.sin(wavePhase) * 0.5 + 0.5  // 0 = blue, 1 = purple

          // While fading in, blend from static gradient toward full wave
          const blendW = tpos * 0.7 * (1 - waveAmt) + w * waveAmt

          cr = Math.round(BLUE[0] + blendW * (PURPLE[0] - BLUE[0]))
          cg = Math.round(BLUE[1] + blendW * (PURPLE[1] - BLUE[1]))
          cb = Math.round(BLUE[2] + blendW * (PURPLE[2] - BLUE[2]))
          alpha = 1
        }

        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${cr},${cg},${cb},${alpha})`
        ctx.fill()
      }

      // ── Phase transitions ──────────────────────────────────────
      if (formPhase > EASE_IN_FRAMES && settled > particles.length * 0.96) {
        if (settledAt < 0) settledAt = frame

        if (!notifiedRef.current) {
          notifiedRef.current = true
          onCompleteRef.current?.()
        }
      }

      frameId = requestAnimationFrame(draw)
    }

    init()

    const onResize = () => {
      width  = canvas.width  = window.innerWidth
      height = canvas.height = window.innerHeight
      init()
    }
    window.addEventListener('resize', onResize)
    return () => {
      cancelAnimationFrame(frameId)
      window.removeEventListener('resize', onResize)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{ display: 'block', width: '100%', height: '100%' }}
    />
  )
}

function sampleTextPixels(text, width, height) {
  const off = document.createElement('canvas')
  off.width  = width
  off.height = height
  const ctx  = off.getContext('2d')

  const fontSize = Math.min(Math.floor(width * 0.27), 260)
  ctx.font          = `900 ${fontSize}px "Inter", "Arial Black", "Impact", sans-serif`
  ctx.fillStyle     = '#ffffff'
  ctx.textAlign     = 'center'
  ctx.textBaseline  = 'middle'
  ctx.fillText(text, width / 2, height / 2)

  const { data } = ctx.getImageData(0, 0, width, height)
  const points = []
  const gap    = 5

  for (let y = 0; y < height; y += gap) {
    for (let x = 0; x < width; x += gap) {
      if (data[(y * width + x) * 4 + 3] > 128) points.push({ x, y })
    }
  }
  return points
}
