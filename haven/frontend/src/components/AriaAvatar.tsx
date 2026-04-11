'use client'
import { useEffect, useRef, useState } from 'react'

interface AriaAvatarProps {
  mood: 'idle' | 'listening' | 'talking'
  size?: number
}

export default function AriaAvatar({ mood, size = 120 }: AriaAvatarProps) {
  const [mouthOpen, setMouthOpen] = useState(0)
  const [blinkState, setBlinkState] = useState(1)
  const [headTilt, setHeadTilt] = useState(0)
  const [eyebrowRaise, setEyebrowRaise] = useState(0)
  const talkInterval = useRef<ReturnType<typeof setInterval> | null>(null)
  const blinkTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Talking animation - mouth opens and closes randomly
  useEffect(() => {
    if (mood === 'talking') {
      talkInterval.current = setInterval(() => {
        setMouthOpen(Math.random() * 12 + 2)
        setHeadTilt((Math.random() - 0.5) * 4)
        setEyebrowRaise(Math.random() * 3)
      }, 120)
    } else {
      if (talkInterval.current) clearInterval(talkInterval.current)
      setMouthOpen(0)
      setHeadTilt(0)
      setEyebrowRaise(0)
    }
    return () => { if (talkInterval.current) clearInterval(talkInterval.current) }
  }, [mood])

  // Listening animation - subtle head tilt
  useEffect(() => {
    if (mood === 'listening') {
      setHeadTilt(3)
      setEyebrowRaise(2)
    }
  }, [mood])

  // Blinking animation
  useEffect(() => {
    function scheduleBlink() {
      const delay = 2000 + Math.random() * 3000
      blinkTimeout.current = setTimeout(() => {
        setBlinkState(0)
        setTimeout(() => {
          setBlinkState(1)
          scheduleBlink()
        }, 150)
      }, delay)
    }
    scheduleBlink()
    return () => { if (blinkTimeout.current) clearTimeout(blinkTimeout.current) }
  }, [])

  const s = size
  const cx = s / 2
  const cy = s / 2
  const faceR = s * 0.38

  // Colors based on mood
  const moodGlow = mood === 'talking'
    ? '#22c55e'
    : mood === 'listening'
      ? '#a855f7'
      : '#be185d'

  const skinBase = '#f9a8d4'
  const skinDark = '#f472b6'
  const hairColor = '#1a0a12'
  const eyeColor = '#be185d'

  // Eye height based on blink
  const eyeH = blinkState * 7

  // Mouth path
  const mouthY = cy + faceR * 0.35
  const mouthW = faceR * 0.45
  const mouthPath = mouthOpen > 1
    ? `M ${cx - mouthW} ${mouthY} Q ${cx} ${mouthY + mouthOpen} ${cx + mouthW} ${mouthY} Q ${cx} ${mouthY - mouthOpen * 0.3} ${cx - mouthW} ${mouthY}`
    : `M ${cx - mouthW} ${mouthY} Q ${cx} ${mouthY + 4} ${cx + mouthW} ${mouthY}`

  return (
    <div style={{
      position: 'relative',
      width: s,
      height: s,
      filter: `drop-shadow(0 0 ${mood === 'talking' ? 16 : 8}px ${moodGlow}${mood === 'talking' ? '99' : '44'})`,
      transition: 'filter 0.5s ease',
    }}>
      <svg
        width={s}
        height={s}
        viewBox={`0 0 ${s} ${s}`}
        style={{
          transform: `rotate(${headTilt}deg)`,
          transition: mood === 'talking' ? 'transform 0.1s ease' : 'transform 0.4s ease',
        }}
      >
        <defs>
          <radialGradient id="faceGrad" cx="45%" cy="40%" r="60%">
            <stop offset="0%" stopColor="#fce7f3" />
            <stop offset="60%" stopColor={skinBase} />
            <stop offset="100%" stopColor={skinDark} />
          </radialGradient>
          <radialGradient id="glowGrad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={moodGlow} stopOpacity="0.3" />
            <stop offset="100%" stopColor={moodGlow} stopOpacity="0" />
          </radialGradient>
          <radialGradient id="cheekGrad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#f9a8d4" stopOpacity="0.7" />
            <stop offset="100%" stopColor="#f9a8d4" stopOpacity="0" />
          </radialGradient>
          <clipPath id="faceClip">
            <ellipse cx={cx} cy={cy + faceR * 0.05} rx={faceR} ry={faceR * 1.08} />
          </clipPath>
        </defs>

        {/* Mood glow ring */}
        <ellipse cx={cx} cy={cy} rx={faceR + 8} ry={faceR + 8} fill="url(#glowGrad)" />

        {/* Hair back */}
        <ellipse cx={cx} cy={cy - faceR * 0.5} rx={faceR * 0.95} ry={faceR * 0.75} fill={hairColor} />

        {/* Neck */}
        <rect x={cx - faceR * 0.22} y={cy + faceR * 0.85} width={faceR * 0.44} height={faceR * 0.3} rx={4} fill={skinBase} />

        {/* Face */}
        <ellipse cx={cx} cy={cy + faceR * 0.05} rx={faceR} ry={faceR * 1.08} fill="url(#faceGrad)" />

        {/* Ear left */}
        <ellipse cx={cx - faceR * 0.98} cy={cy + faceR * 0.1} rx={faceR * 0.12} ry={faceR * 0.18} fill={skinBase} />
        {/* Ear right */}
        <ellipse cx={cx + faceR * 0.98} cy={cy + faceR * 0.1} rx={faceR * 0.12} ry={faceR * 0.18} fill={skinBase} />

        {/* Hair front */}
        <path
          d={`M ${cx - faceR * 0.95} ${cy - faceR * 0.2}
              Q ${cx - faceR * 0.8} ${cy - faceR * 1.15} ${cx - faceR * 0.3} ${cy - faceR * 1.1}
              Q ${cx} ${cy - faceR * 1.25} ${cx + faceR * 0.3} ${cy - faceR * 1.1}
              Q ${cx + faceR * 0.8} ${cy - faceR * 1.15} ${cx + faceR * 0.95} ${cy - faceR * 0.2}
              Q ${cx + faceR * 0.7} ${cy - faceR * 0.6} ${cx} ${cy - faceR * 0.55}
              Q ${cx - faceR * 0.7} ${cy - faceR * 0.6} ${cx - faceR * 0.95} ${cy - faceR * 0.2}`}
          fill={hairColor}
        />

        {/* Side hair strands */}
        <path d={`M ${cx - faceR * 0.95} ${cy - faceR * 0.1} Q ${cx - faceR * 1.1} ${cy + faceR * 0.4} ${cx - faceR * 0.9} ${cy + faceR * 0.7}`}
          stroke={hairColor} strokeWidth={faceR * 0.18} fill="none" strokeLinecap="round" />
        <path d={`M ${cx + faceR * 0.95} ${cy - faceR * 0.1} Q ${cx + faceR * 1.1} ${cy + faceR * 0.4} ${cx + faceR * 0.9} ${cy + faceR * 0.7}`}
          stroke={hairColor} strokeWidth={faceR * 0.18} fill="none" strokeLinecap="round" />

        {/* Eyebrows */}
        <path
          d={`M ${cx - faceR * 0.5} ${cy - faceR * 0.28 - eyebrowRaise} Q ${cx - faceR * 0.28} ${cy - faceR * 0.38 - eyebrowRaise} ${cx - faceR * 0.08} ${cy - faceR * 0.28 - eyebrowRaise}`}
          stroke={hairColor} strokeWidth={faceR * 0.07} fill="none" strokeLinecap="round"
          style={{ transition: 'all 0.2s ease' }}
        />
        <path
          d={`M ${cx + faceR * 0.08} ${cy - faceR * 0.28 - eyebrowRaise} Q ${cx + faceR * 0.28} ${cy - faceR * 0.38 - eyebrowRaise} ${cx + faceR * 0.5} ${cy - faceR * 0.28 - eyebrowRaise}`}
          stroke={hairColor} strokeWidth={faceR * 0.07} fill="none" strokeLinecap="round"
          style={{ transition: 'all 0.2s ease' }}
        />

        {/* Eyes white */}
        <ellipse cx={cx - faceR * 0.3} cy={cy - faceR * 0.1} rx={faceR * 0.18} ry={eyeH} fill="white" style={{ transition: 'ry 0.08s ease' }} />
        <ellipse cx={cx + faceR * 0.3} cy={cy - faceR * 0.1} rx={faceR * 0.18} ry={eyeH} fill="white" style={{ transition: 'ry 0.08s ease' }} />

        {/* Iris */}
        <ellipse cx={cx - faceR * 0.3} cy={cy - faceR * 0.1} rx={faceR * 0.12} ry={Math.min(eyeH * 0.9, faceR * 0.12)} fill={eyeColor} style={{ transition: 'ry 0.08s ease' }} />
        <ellipse cx={cx + faceR * 0.3} cy={cy - faceR * 0.1} rx={faceR * 0.12} ry={Math.min(eyeH * 0.9, faceR * 0.12)} fill={eyeColor} style={{ transition: 'ry 0.08s ease' }} />

        {/* Pupil */}
        <ellipse cx={cx - faceR * 0.3} cy={cy - faceR * 0.1} rx={faceR * 0.06} ry={Math.min(eyeH * 0.5, faceR * 0.06)} fill="#1a0a12" style={{ transition: 'ry 0.08s ease' }} />
        <ellipse cx={cx + faceR * 0.3} cy={cy - faceR * 0.1} rx={faceR * 0.06} ry={Math.min(eyeH * 0.5, faceR * 0.06)} fill="#1a0a12" style={{ transition: 'ry 0.08s ease' }} />

        {/* Eye shine */}
        <ellipse cx={cx - faceR * 0.26} cy={cy - faceR * 0.14} rx={faceR * 0.035} ry={Math.min(eyeH * 0.3, faceR * 0.035)} fill="white" opacity={0.9} style={{ transition: 'ry 0.08s ease' }} />
        <ellipse cx={cx + faceR * 0.34} cy={cy - faceR * 0.14} rx={faceR * 0.035} ry={Math.min(eyeH * 0.3, faceR * 0.035)} fill="white" opacity={0.9} style={{ transition: 'ry 0.08s ease' }} />

        {/* Nose */}
        <path d={`M ${cx - faceR * 0.07} ${cy + faceR * 0.08} Q ${cx} ${cy + faceR * 0.22} ${cx + faceR * 0.07} ${cy + faceR * 0.08}`}
          stroke="#e879a0" strokeWidth={faceR * 0.04} fill="none" strokeLinecap="round" opacity={0.6} />

        {/* Cheeks blush */}
        <ellipse cx={cx - faceR * 0.58} cy={cy + faceR * 0.18} rx={faceR * 0.2} ry={faceR * 0.12} fill="url(#cheekGrad)" />
        <ellipse cx={cx + faceR * 0.58} cy={cy + faceR * 0.18} rx={faceR * 0.2} ry={faceR * 0.12} fill="url(#cheekGrad)" />

        {/* Mouth */}
        <path d={mouthPath} fill={mouthOpen > 1 ? '#be185d' : 'none'}
          stroke="#be185d" strokeWidth={faceR * 0.05} strokeLinecap="round"
          style={{ transition: mood === 'talking' ? 'none' : 'd 0.2s ease' }}
        />

        {/* Teeth when mouth open */}
        {mouthOpen > 4 && (
          <path d={`M ${cx - mouthW * 0.7} ${mouthY + 1} L ${cx + mouthW * 0.7} ${mouthY + 1} L ${cx + mouthW * 0.7} ${mouthY + mouthOpen * 0.5} L ${cx - mouthW * 0.7} ${mouthY + mouthOpen * 0.5} Z`}
            fill="white" clipPath="url(#faceClip)" />
        )}

        {/* Flower hair accessory */}
        <g transform={`translate(${cx + faceR * 0.55}, ${cy - faceR * 0.85})`}>
          {[0, 60, 120, 180, 240, 300].map(angle => (
            <ellipse key={angle}
             cx={Number((Math.cos(angle * Math.PI / 180) * 5).toFixed(2))}
             cy={Number((Math.sin(angle * Math.PI / 180) * 5).toFixed(2))}
              rx={4} ry={2.5}
              fill="#fce7f3"
              transform={`rotate(${angle}, ${Math.cos(angle * Math.PI / 180) * 5}, ${Math.sin(angle * Math.PI / 180) * 5})`}
            />
          ))}
          <circle cx={0} cy={0} r={3.5} fill="#be185d" />
        </g>

        {/* Mood indicator dots */}
        {mood === 'talking' && (
          <g>
            {[0, 1, 2].map(i => (
              <circle key={i}
                cx={cx + faceR * 1.3 + i * 8}
                cy={cy}
                r={3}
                fill={moodGlow}
                opacity={0.8}
              >
                <animate attributeName="cy" values={`${cy};${cy - 6};${cy}`} dur="0.6s" begin={`${i * 0.2}s`} repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.8;0.3;0.8" dur="0.6s" begin={`${i * 0.2}s`} repeatCount="indefinite" />
              </circle>
            ))}
          </g>
        )}
      </svg>

      {/* Mood label */}
      <div style={{
        position: 'absolute', bottom: -20, left: '50%', transform: 'translateX(-50%)',
        fontSize: '0.65rem', fontWeight: 600, color: moodGlow,
        whiteSpace: 'nowrap', transition: 'color 0.4s ease',
        textShadow: `0 0 8px ${moodGlow}44`,
      }}>
        {mood === 'idle' ? '● Ready' : mood === 'listening' ? '◉ Listening' : '◈ Speaking'}
      </div>
    </div>
  )
}