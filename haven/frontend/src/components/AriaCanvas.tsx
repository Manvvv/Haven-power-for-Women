'use client'
import { useEffect, useRef, useImperativeHandle, forwardRef } from 'react'


export type AvatarMood = 'idle' | 'listening' | 'talking'

export interface AvatarHandle {
  setMood: (mood: AvatarMood) => void
}

interface Props {
  size?: number
}

const AriaCanvas = forwardRef<AvatarHandle, Props>(({ size = 320 }, ref) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stateRef = useRef({
    mood: 'idle' as AvatarMood,
    mouthOpen: 0,
    mouthTarget: 0,
    blinkVal: 0,
    blinkPhase: 0,
    blinkTimer: 0,
    blinkInterval: 3.5,
    browLift: 0,
    browTarget: 0,
    headTiltX: 0,
    headTiltY: 0,
    headTiltTargetX: 0,
    headTiltTargetY: 0,
    t: 0,
    talkPhase: 0,
    breathPhase: 0,
    eyeGlow: 0,
  })
  const rafRef = useRef<number>(0)
  const talkIntervalRef = useRef<any>(null)

  useImperativeHandle(ref, () => ({
    setMood: (mood: AvatarMood) => {
      const s = stateRef.current
      s.mood = mood
      clearInterval(talkIntervalRef.current)
      if (mood === 'talking') {
        talkIntervalRef.current = setInterval(() => {
          s.mouthTarget = 0.15 + Math.random() * 0.55
          s.headTiltTargetX = (Math.random() - 0.5) * 0.06
          s.headTiltTargetY = (Math.random() - 0.5) * 0.05
          s.eyeGlow = 0.3 + Math.random() * 0.4
        }, 100 + Math.random() * 80)
      } else if (mood === 'listening') {
        s.mouthTarget = 0.05
        s.browTarget = 1
        s.headTiltTargetX = -0.04
        s.headTiltTargetY = 0.03
        s.eyeGlow = 0.5
      } else {
        s.mouthTarget = 0
        s.browTarget = 0
        s.headTiltTargetX = 0
        s.headTiltTargetY = 0
        s.eyeGlow = 0
      }
    }
  }))

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const s = stateRef.current
    const DPR = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = size * DPR
    canvas.height = size * DPR
    canvas.style.width = size + 'px'
    canvas.style.height = size + 'px'
    ctx.scale(DPR, DPR)

    const W = size, H = size
    const CX = W / 2, CY = H / 2

    const lerp = (a: number, b: number, t: number) => a + (b - a) * t

    const draw = () => {
      s.t += 0.016
      s.breathPhase += 0.016

      // Smooth lerp all values
      s.mouthOpen = lerp(s.mouthOpen, s.mouthTarget, 0.25)
      s.browLift = lerp(s.browLift, s.browTarget, 0.1)
      s.headTiltX = lerp(s.headTiltX, s.headTiltTargetX, 0.08)
      s.headTiltY = lerp(s.headTiltY, s.headTiltTargetY, 0.08)

      // Idle head sway
      if (s.mood === 'idle') {
        s.headTiltTargetX = Math.sin(s.t * 0.3) * 0.018
        s.headTiltTargetY = Math.sin(s.t * 0.22) * 0.012
      }

      // Blink
      s.blinkTimer += 0.016
      if (s.blinkTimer >= s.blinkInterval) {
        s.blinkPhase = 1
        s.blinkTimer = 0
        s.blinkInterval = 2.5 + Math.random() * 3.5
      }
      if (s.blinkPhase > 0) {
        s.blinkPhase -= 0.12
        if (s.blinkPhase < 0) s.blinkPhase = 0
        s.blinkVal = Math.sin(s.blinkPhase * Math.PI) * 1.2
      } else {
        s.blinkVal = 0
      }

      ctx.clearRect(0, 0, W, H)

      // Body offset from breathing + head tilt
      const breathY = Math.sin(s.breathPhase * 0.9) * 2.5
      const tx = CX + s.headTiltY * 30
      const ty = CY + breathY + s.headTiltX * 20

      ctx.save()
      ctx.translate(tx, ty)
      ctx.rotate(s.headTiltY * 0.12)

      drawAvatar(ctx, W, H, s)

      ctx.restore()
      rafRef.current = requestAnimationFrame(draw)
    }

    rafRef.current = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(rafRef.current)
      clearInterval(talkIntervalRef.current)
    }
  }, [size])

  return (
    <canvas
      ref={canvasRef}
      style={{ display: 'block', borderRadius: '50%' }}
    />
  )
})

AriaCanvas.displayName = 'AriaCanvas'
export default AriaCanvas

function drawAvatar(ctx: CanvasRenderingContext2D, W: number, H: number, s: any) {
  const lerp = (a: number, b: number, t: number) => a + (b - a) * t
  const R = W * 0.31
  const t = s.t

  // ── NECK ──────────────────────────────────────────
  ctx.save()
  const neckGrad = ctx.createLinearGradient(-20, R * 0.72, 20, R * 1.1)
  neckGrad.addColorStop(0, '#f5c6a0')
  neckGrad.addColorStop(1, '#ebb88a')
  ctx.fillStyle = neckGrad
  ctx.beginPath()
  ctx.moveTo(-R * 0.18, R * 0.72)
  ctx.bezierCurveTo(-R * 0.2, R * 0.95, -R * 0.16, R * 1.05, 0, R * 1.08)
  ctx.bezierCurveTo(R * 0.16, R * 1.05, R * 0.2, R * 0.95, R * 0.18, R * 0.72)
  ctx.closePath()
  ctx.fill()
  ctx.restore()

  // ── SHOULDERS / BODY ──────────────────────────────
  ctx.save()
  const bodyGrad = ctx.createLinearGradient(-R * 0.9, R * 0.9, R * 0.9, R * 1.6)
  bodyGrad.addColorStop(0, '#fce7f3')
  bodyGrad.addColorStop(0.4, '#f9d0e8')
  bodyGrad.addColorStop(1, '#f0b8d8')
  ctx.fillStyle = bodyGrad
  ctx.beginPath()
  ctx.moveTo(-R * 0.95, R * 1.6)
  ctx.bezierCurveTo(-R * 0.95, R * 1.1, -R * 0.5, R * 0.95, 0, R * 1.05)
  ctx.bezierCurveTo(R * 0.5, R * 0.95, R * 0.95, R * 1.1, R * 0.95, R * 1.6)
  ctx.closePath()
  ctx.fill()

  // Collar detail
  ctx.strokeStyle = 'rgba(190,24,93,0.15)'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.moveTo(-R * 0.25, R * 1.05)
  ctx.bezierCurveTo(-R * 0.12, R * 1.18, R * 0.12, R * 1.18, R * 0.25, R * 1.05)
  ctx.stroke()
  ctx.restore()

  // ── FACE BASE ──────────────────────────────────────
  ctx.save()
  const faceGrad = ctx.createRadialGradient(-R * 0.15, -R * 0.2, R * 0.05, 0, 0, R)
  faceGrad.addColorStop(0, '#fde8cc')
  faceGrad.addColorStop(0.5, '#f5c6a0')
  faceGrad.addColorStop(1, '#ebb88a')
  ctx.fillStyle = faceGrad
  ctx.beginPath()
  ctx.ellipse(0, 0, R * 0.82, R * 0.92, 0, 0, Math.PI * 2)
  ctx.fill()

  // Face shadow
  const shadowGrad = ctx.createRadialGradient(0, R * 0.3, R * 0.3, 0, R * 0.4, R * 0.9)
  shadowGrad.addColorStop(0, 'rgba(0,0,0,0)')
  shadowGrad.addColorStop(1, 'rgba(120,60,20,0.12)')
  ctx.fillStyle = shadowGrad
  ctx.beginPath()
  ctx.ellipse(0, 0, R * 0.82, R * 0.92, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()

  // ── EARS ───────────────────────────────────────────
  ctx.save()
  ctx.fillStyle = '#f0b8a0'
  ctx.beginPath(); ctx.ellipse(-R * 0.83, R * 0.05, R * 0.1, R * 0.14, -0.2, 0, Math.PI * 2); ctx.fill()
  ctx.beginPath(); ctx.ellipse(R * 0.83, R * 0.05, R * 0.1, R * 0.14, 0.2, 0, Math.PI * 2); ctx.fill()

  // Earrings
  ctx.fillStyle = '#d4af37'
  ctx.shadowColor = '#d4af37'
  ctx.shadowBlur = 4
  ctx.beginPath(); ctx.arc(-R * 0.88, R * 0.14, R * 0.04, 0, Math.PI * 2); ctx.fill()
  ctx.beginPath(); ctx.arc(R * 0.88, R * 0.14, R * 0.04, 0, Math.PI * 2); ctx.fill()
  ctx.shadowBlur = 0
  ctx.restore()

  // ── HAIR BACK ──────────────────────────────────────
  ctx.save()
  ctx.fillStyle = '#2c1810'
  ctx.beginPath()
  ctx.ellipse(0, -R * 0.45, R * 0.85, R * 0.72, 0, 0, Math.PI * 2)
  ctx.fill()

  // Long side strands
  ctx.fillStyle = '#251208'
  ctx.beginPath()
  ctx.moveTo(-R * 0.75, -R * 0.2)
  ctx.bezierCurveTo(-R * 1.0, R * 0.2, -R * 1.05, R * 0.6, -R * 0.9, R * 0.85)
  ctx.bezierCurveTo(-R * 0.78, R * 0.88, -R * 0.65, R * 0.8, -R * 0.62, R * 0.65)
  ctx.bezierCurveTo(-R * 0.7, R * 0.4, -R * 0.7, R * 0.1, -R * 0.6, -R * 0.15)
  ctx.closePath()
  ctx.fill()

  ctx.beginPath()
  ctx.moveTo(R * 0.75, -R * 0.2)
  ctx.bezierCurveTo(R * 1.0, R * 0.2, R * 1.05, R * 0.6, R * 0.9, R * 0.85)
  ctx.bezierCurveTo(R * 0.78, R * 0.88, R * 0.65, R * 0.8, R * 0.62, R * 0.65)
  ctx.bezierCurveTo(R * 0.7, R * 0.4, R * 0.7, R * 0.1, R * 0.6, -R * 0.15)
  ctx.closePath()
  ctx.fill()
  ctx.restore()

  // ── HAIR FRONT ─────────────────────────────────────
  ctx.save()
  const hairGrad = ctx.createLinearGradient(0, -R, 0, -R * 0.3)
  hairGrad.addColorStop(0, '#3d1f12')
  hairGrad.addColorStop(0.6, '#2c1810')
  hairGrad.addColorStop(1, '#1a0a08')
  ctx.fillStyle = hairGrad
  ctx.beginPath()
  ctx.moveTo(-R * 0.82, -R * 0.1)
  ctx.bezierCurveTo(-R * 0.9, -R * 0.5, -R * 0.7, -R * 0.95, -R * 0.3, -R * 0.9)
  ctx.bezierCurveTo(-R * 0.1, -R * 1.05, R * 0.1, -R * 1.05, R * 0.3, -R * 0.9)
  ctx.bezierCurveTo(R * 0.7, -R * 0.95, R * 0.9, -R * 0.5, R * 0.82, -R * 0.1)
  ctx.bezierCurveTo(R * 0.65, -R * 0.25, R * 0.3, -R * 0.3, 0, -R * 0.28)
  ctx.bezierCurveTo(-R * 0.3, -R * 0.3, -R * 0.65, -R * 0.25, -R * 0.82, -R * 0.1)
  ctx.closePath()
  ctx.fill()
  ctx.restore()

  // ── HAIR BUN ──────────────────────────────────────
  ctx.save()
  const bunX = R * 0.55, bunY = -R * 0.78
  const bunGrad = ctx.createRadialGradient(bunX - 5, bunY - 5, 2, bunX, bunY, R * 0.22)
  bunGrad.addColorStop(0, '#4a2018')
  bunGrad.addColorStop(1, '#1a0a08')
  ctx.fillStyle = bunGrad
  ctx.beginPath()
  ctx.ellipse(bunX, bunY, R * 0.22, R * 0.18, 0.4, 0, Math.PI * 2)
  ctx.fill()

  // Bun strand detail
  ctx.strokeStyle = '#3d1f12'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.arc(bunX, bunY, R * 0.14, 0.3, Math.PI * 1.2)
  ctx.stroke()
  ctx.restore()

  // ── FLOWER PIN ───────────────────────────────────
  ctx.save()
  ctx.translate(bunX - R * 0.06, bunY - R * 0.18)
  for (let i = 0; i < 6; i++) {
    const angle = (i / 6) * Math.PI * 2 + t * 0.4
    const px = Math.cos(angle) * R * 0.075
    const py = Math.sin(angle) * R * 0.075
    ctx.fillStyle = i % 2 === 0 ? '#fce7f3' : '#f9a8d4'
    ctx.beginPath()
    ctx.ellipse(px, py, R * 0.055, R * 0.04, angle, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.fillStyle = '#be185d'
  ctx.beginPath()
  ctx.arc(0, 0, R * 0.045, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = 'rgba(255,255,255,0.5)'
  ctx.beginPath()
  ctx.arc(-R * 0.015, -R * 0.015, R * 0.016, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()

  // ── BLUSH CHEEKS ─────────────────────────────────
  ctx.save()
  const blushOpacity = 0.28 + (s.mood === 'talking' ? 0.08 : 0)
  const makeBlush = (x: number) => {
    const g = ctx.createRadialGradient(x, R * 0.18, 0, x, R * 0.18, R * 0.22)
    g.addColorStop(0, `rgba(249,130,170,${blushOpacity})`)
    g.addColorStop(1, 'rgba(249,130,170,0)')
    return g
  }
  ctx.fillStyle = makeBlush(-R * 0.45)
  ctx.beginPath(); ctx.ellipse(-R * 0.45, R * 0.18, R * 0.22, R * 0.16, 0, 0, Math.PI * 2); ctx.fill()
  ctx.fillStyle = makeBlush(R * 0.45)
  ctx.beginPath(); ctx.ellipse(R * 0.45, R * 0.18, R * 0.22, R * 0.16, 0, 0, Math.PI * 2); ctx.fill()
  ctx.restore()

  // ── EYEBROWS ─────────────────────────────────────
  ctx.save()
  const browY = -R * 0.28 - s.browLift * R * 0.06
  const browCurve = s.mood === 'listening' ? 0.04 : 0
  ctx.strokeStyle = '#2c1810'
  ctx.lineWidth = R * 0.048
  ctx.lineCap = 'round'

  ctx.beginPath()
  ctx.moveTo(-R * 0.52, browY + browCurve)
  ctx.bezierCurveTo(-R * 0.38, browY - R * 0.055, -R * 0.24, browY - R * 0.055, -R * 0.14, browY + R * 0.01)
  ctx.stroke()

  ctx.beginPath()
  ctx.moveTo(R * 0.52, browY + browCurve)
  ctx.bezierCurveTo(R * 0.38, browY - R * 0.055, R * 0.24, browY - R * 0.055, R * 0.14, browY + R * 0.01)
  ctx.stroke()
  ctx.restore()

  // ── EYES ─────────────────────────────────────────
  const eyeY = -R * 0.12
  const eyeXL = -R * 0.3, eyeXR = R * 0.3
  const eyeW = R * 0.22, eyeH = R * 0.16
  const blinkScale = Math.max(0, 1 - s.blinkVal)

  const drawEye = (ex: number) => {
    ctx.save()
    ctx.translate(ex, eyeY)

    // Shadow
    ctx.fillStyle = 'rgba(60,20,40,0.12)'
    ctx.beginPath()
    ctx.ellipse(2, 3, eyeW * 0.9, eyeH * 0.7, 0, 0, Math.PI * 2)
    ctx.fill()

    // White
    ctx.fillStyle = '#fffaf8'
    ctx.beginPath()
    ctx.ellipse(0, 0, eyeW, eyeH, 0, 0, Math.PI * 2)
    ctx.fill()

    // Iris
    const irisGrad = ctx.createRadialGradient(-eyeW * 0.15, -eyeH * 0.2, eyeH * 0.05, 0, 0, eyeH * 0.75)
    irisGrad.addColorStop(0, '#c4205a')
    irisGrad.addColorStop(0.5, '#9d174d')
    irisGrad.addColorStop(1, '#6d1035')
    ctx.fillStyle = irisGrad
    ctx.beginPath()
    ctx.arc(0, 0, eyeH * 0.72, 0, Math.PI * 2)
    ctx.fill()

    // Pupil
    ctx.fillStyle = '#0a0005'
    ctx.beginPath()
    ctx.arc(0, 0, eyeH * 0.36, 0, Math.PI * 2)
    ctx.fill()

    // Eye shine
    ctx.fillStyle = 'rgba(255,255,255,0.88)'
    ctx.beginPath()
    ctx.arc(-eyeH * 0.22, -eyeH * 0.28, eyeH * 0.18, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = 'rgba(255,255,255,0.45)'
    ctx.beginPath()
    ctx.arc(eyeH * 0.2, eyeH * 0.1, eyeH * 0.1, 0, Math.PI * 2)
    ctx.fill()

    // Mood glow ring
    if (s.eyeGlow > 0) {
      ctx.strokeStyle = s.mood === 'talking' ? `rgba(34,197,94,${s.eyeGlow * 0.5})` : `rgba(168,85,247,${s.eyeGlow * 0.5})`
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(0, 0, eyeH * 0.85, 0, Math.PI * 2)
      ctx.stroke()
    }

    // Eyelid blink
    ctx.fillStyle = '#f5c6a0'
    ctx.beginPath()
    ctx.ellipse(0, -eyeH * (1 - blinkScale * 0.5), eyeW * 1.05, eyeH * (1.1 * blinkScale + 0.02), 0, Math.PI, Math.PI * 2)
    ctx.fill()

    // Top lash
    ctx.fillStyle = '#1a0a08'
    ctx.beginPath()
    ctx.ellipse(0, -eyeH * 0.88, eyeW * 1.02, eyeH * 0.22, 0, Math.PI, Math.PI * 2)
    ctx.fill()

    // Lash fringe
    for (let i = -3; i <= 3; i++) {
      const lx = (i / 3) * eyeW * 0.85
      const ly = -eyeH * 0.9 - Math.abs(i) * 0.5
      ctx.strokeStyle = '#1a0a08'
      ctx.lineWidth = 1.2
      ctx.beginPath()
      ctx.moveTo(lx, ly)
      ctx.lineTo(lx + (i * 1.5), ly - eyeH * 0.22)
      ctx.stroke()
    }

    ctx.restore()
  }

  drawEye(eyeXL)
  drawEye(eyeXR)

  // ── NOSE ─────────────────────────────────────────
  ctx.save()
  ctx.strokeStyle = 'rgba(180,100,60,0.35)'
  ctx.lineWidth = R * 0.028
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(-R * 0.1, R * 0.1)
  ctx.bezierCurveTo(-R * 0.12, R * 0.2, -R * 0.08, R * 0.24, 0, R * 0.24)
  ctx.bezierCurveTo(R * 0.08, R * 0.24, R * 0.12, R * 0.2, R * 0.1, R * 0.1)
  ctx.stroke()

  ctx.fillStyle = 'rgba(180,100,60,0.2)'
  ctx.beginPath()
  ctx.ellipse(-R * 0.1, R * 0.22, R * 0.055, R * 0.038, -0.2, 0, Math.PI * 2)
  ctx.fill()
  ctx.beginPath()
  ctx.ellipse(R * 0.1, R * 0.22, R * 0.055, R * 0.038, 0.2, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()

  // ── MOUTH ────────────────────────────────────────
 // ── MOUTH (PERFECTLY SYNCED) ───────────────────────
ctx.save()

const mY = R * 0.46
const mOpen = s.mouthOpen
const w = R * (0.26 + mOpen * 0.12)

// Shared control points (SAME for everything)
const topY = mY - mOpen * R * 0.15
const bottomY = mY + mOpen * R * 0.55

// 👉 Create ONE path
const mouthPath = new Path2D()

mouthPath.moveTo(-w, mY)

mouthPath.bezierCurveTo(
  -w * 0.6,
  bottomY,
  w * 0.6,
  bottomY,
  w,
  mY
)

mouthPath.bezierCurveTo(
  w * 0.6,
  topY,
  -w * 0.6,
  topY,
  -w,
  mY
)

mouthPath.closePath()

// ── INNER MOUTH ──
if (mOpen > 0.03) {
  ctx.fillStyle = '#1a0010'
  ctx.fill(mouthPath)
}

// ── TEETH (CLIPPED INSIDE SAME SHAPE) ──
if (mOpen > 0.08) {
  ctx.save()
  ctx.clip(mouthPath)

  ctx.fillStyle = '#fff8f5'
  ctx.beginPath()
  ctx.ellipse(0, mY + mOpen * R * 0.12, w * 0.55, mOpen * R * 0.25, 0, 0, Math.PI * 2)
  ctx.fill()

  ctx.restore()
}

// ── UPPER LIP (USES SAME TOP CURVE) ──
const lipGrad = ctx.createLinearGradient(0, topY, 0, mY)
lipGrad.addColorStop(0, '#e0527a')
lipGrad.addColorStop(1, '#be185d')

ctx.fillStyle = lipGrad

ctx.beginPath()
ctx.moveTo(-w, topY)

ctx.bezierCurveTo(
  -w * 0.6,
  topY - R * 0.08,
  w * 0.6,
  topY - R * 0.08,
  w,
  topY
)

ctx.lineTo(w, mY)
ctx.lineTo(-w, mY)
ctx.closePath()
ctx.fill()

// ── LOWER LIP (USES SAME BOTTOM CURVE) ──
const lowerGrad = ctx.createLinearGradient(0, mY, 0, bottomY)
lowerGrad.addColorStop(0, '#c9205f')
lowerGrad.addColorStop(1, '#a01848')

ctx.fillStyle = lowerGrad

ctx.beginPath()
ctx.moveTo(-w, mY)

ctx.bezierCurveTo(
  -w * 0.6,
  bottomY + R * 0.015,
  w * 0.6,
  bottomY + R * 0.015,
  w,
  mY
)
ctx.closePath()
ctx.fill()

// ── SHINE ──
ctx.fillStyle = 'rgba(255,200,220,0.35)'
ctx.beginPath()
ctx.ellipse(0, mY + R * 0.07, w * 0.35, R * 0.04, 0, 0, Math.PI * 2)
ctx.fill()

ctx.restore()

ctx.restore()
  // Corner dimples
  ctx.fillStyle = 'rgba(150,40,80,0.35)'
  ctx.beginPath(); ctx.arc(-R * 0.28, mY, R * 0.022, 0, Math.PI * 2); ctx.fill()
  ctx.beginPath(); ctx.arc(R * 0.28, mY, R * 0.022, 0, Math.PI * 2); ctx.fill()
  ctx.restore()

  // ── FACE HIGHLIGHT / SKIN SHEEN ──────────────────
  ctx.save()
  const sheenGrad = ctx.createRadialGradient(-R * 0.2, -R * 0.35, 0, -R * 0.2, -R * 0.35, R * 0.5)
  sheenGrad.addColorStop(0, 'rgba(255,255,255,0.22)')
  sheenGrad.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = sheenGrad
  ctx.beginPath()
  ctx.ellipse(0, 0, R * 0.82, R * 0.92, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()

  // ── MOOD AURA ─────────────────────────────────────
  if (s.mood !== 'idle') {
    ctx.save()
    const auraColor = s.mood === 'talking' ? '34,197,94' : '168,85,247'
    const auraGrad = ctx.createRadialGradient(0, 0, R * 0.85, 0, 0, R * 1.15)
    auraGrad.addColorStop(0, `rgba(${auraColor},0.18)`)
    auraGrad.addColorStop(1, `rgba(${auraColor},0)`)
    ctx.fillStyle = auraGrad
    ctx.beginPath()
    ctx.arc(0, 0, R * 1.15, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
  }
}