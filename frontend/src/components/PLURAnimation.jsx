import { useEffect, useRef } from 'react'

export default function PLURAnimation({ onComplete }) {
  const canvasRef = useRef(null)
  const notifiedRef = useRef(false)

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

    async function init() {
      await document.fonts.ready

      const targets = sampleTextPixels('PLUR', width, height)

      particles = targets.map(t => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 8,
        vy: (Math.random() - 0.5) * 8,
        tx: t.x,
        ty: t.y,
        r: Math.random() * 1.4 + 0.4,
      }))

      cancelAnimationFrame(frameId)
      frameId = requestAnimationFrame(draw)
    }

    function draw() {
      ctx.clearRect(0, 0, width, height)

      let settled = 0

      for (const p of particles) {
        const dx = p.tx - p.x
        const dy = p.ty - p.y

        p.vx = (p.vx + dx * 0.055) * 0.84
        p.vy = (p.vy + dy * 0.055) * 0.84
        p.x += p.vx
        p.y += p.vy

        if (Math.hypot(dx, dy) < 1.5) settled++

        // Blue-to-indigo gradient across the text width
        const t = Math.max(0, Math.min(1, (p.tx - width * 0.12) / (width * 0.76)))
        const r = Math.round(59 + t * 99)
        const g = Math.round(130 - t * 90)
        const b = Math.round(246 - t * 30)

        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgb(${r},${g},${b})`
        ctx.fill()
      }

      if (particles.length > 0 && settled > particles.length * 0.96 && !notifiedRef.current) {
        notifiedRef.current = true
        onComplete?.()
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
  }, [onComplete])

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
