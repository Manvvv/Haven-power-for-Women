'use client'
import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'

const SECRET = '1810'

export default function CalculatorPage() {
  const router = useRouter()
  const [display, setDisplay] = useState('0')
  const [prev, setPrev] = useState('')
  const [op, setOp] = useState('')
  const [fresh, setFresh] = useState(true)
  const [typed, setTyped] = useState('')
  const [flash, setFlash] = useState(false)

  useEffect(() => {
    if (sessionStorage.getItem('haven_unlocked') === 'true') {
      router.replace('/home')
    }
  }, [router])

  const unlock = () => {
    setFlash(true)
    setTimeout(() => {
      sessionStorage.setItem('haven_unlocked', 'true')
      router.push('/home')
    }, 500)
  }

  const num = (n: string) => {
    const next = fresh || display === '0' ? n : (display + n).slice(0, 12)
    setDisplay(next)
    setFresh(false)
    const t = typed + n
    setTyped(t)
    if (t.slice(-SECRET.length) === SECRET) unlock()
  }

  const opBtn = (o: string) => {
    setPrev(display); setOp(o); setFresh(true); setTyped('')
  }

  const eq = () => {
    if (!op || !prev) return
    const a = parseFloat(prev), b = parseFloat(display)
    const res = op === '+' ? a + b : op === '-' ? a - b : op === '*' ? a * b : b ? a / b : 0
    const s = parseFloat(res.toFixed(8)).toString()
    setDisplay(s.length > 12 ? parseFloat(res.toFixed(3)).toString() : s)
    setPrev(''); setOp(''); setFresh(true); setTyped('')
  }

  const clear = () => { setDisplay('0'); setPrev(''); setOp(''); setFresh(true); setTyped('') }
  const dot = () => { if (!display.includes('.')) setDisplay((fresh ? '0' : display) + '.'); setFresh(false) }
  const pm = () => setDisplay(display.startsWith('-') ? display.slice(1) : '-' + display)
  const pct = () => { setDisplay((parseFloat(display) / 100).toString()); setFresh(true) }

  const activeOp = (o: string) => op === o && !fresh

  const BTNS = [
    [{ l: 'AC', t: 'fn', a: clear }, { l: '+/-', t: 'fn', a: pm }, { l: '%', t: 'fn', a: pct }, { l: '÷', t: 'op', a: () => opBtn('/') }],
    [{ l: '7', t: 'n', a: () => num('7') }, { l: '8', t: 'n', a: () => num('8') }, { l: '9', t: 'n', a: () => num('9') }, { l: '×', t: 'op', a: () => opBtn('*') }],
    [{ l: '4', t: 'n', a: () => num('4') }, { l: '5', t: 'n', a: () => num('5') }, { l: '6', t: 'n', a: () => num('6') }, { l: '−', t: 'op', a: () => opBtn('-') }],
    [{ l: '1', t: 'n', a: () => num('1') }, { l: '2', t: 'n', a: () => num('2') }, { l: '3', t: 'n', a: () => num('3') }, { l: '+', t: 'op', a: () => opBtn('+') }],
    [{ l: '0', t: 'w', a: () => num('0') }, { l: '.', t: 'n', a: dot }, { l: '=', t: 'eq', a: eq }],
  ]

  const getBg = (t: string, l: string) => {
    if (flash) return '#22c55e'
    if (t === 'fn') return '#a0a0a0'
    if (t === 'op' || t === 'eq') {
      const map: any = { '÷': '/', '×': '*', '−': '-', '+': '+' }
      return activeOp(map[l] || l) ? '#ffffff' : '#ff9f0a'
    }
    return '#333333'
  }

  const getColor = (t: string, l: string) => {
    if (flash) return '#ffffff'
    if (t === 'fn') return '#000'
    if (t === 'op' || t === 'eq') {
      const map: any = { '÷': '/', '×': '*', '−': '-', '+': '+' }
      return activeOp(map[l] || l) ? '#ff9f0a' : '#fff'
    }
    return '#fff'
  }

  return (
    <div style={{ minHeight: '100vh', background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: '-apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif' }}>
      <div style={{ width: 320, borderRadius: 44, background: '#1c1c1e', padding: '28px 20px 24px', boxShadow: '0 32px 80px rgba(0,0,0,0.8)', border: '0.5px solid rgba(255,255,255,0.08)' }}>

        {/* Display */}
        <div style={{ textAlign: 'right', padding: '12px 16px 20px', minHeight: 100, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', borderRadius: 16, background: flash ? 'rgba(34,197,94,0.1)' : 'transparent', transition: 'background 0.2s', position: 'relative' }}>
          <div style={{ position: 'absolute', top: 12, left: 16, fontSize: 18, color: 'rgba(255,255,255,0.3)', fontWeight: 400 }}>
            Demo password: 1810
          </div>
          {op && (
            <div style={{ fontSize: 16, color: 'rgba(255,255,255,0.35)', marginBottom: 4 }}>
              {prev} {op === '/' ? '÷' : op === '*' ? '×' : op === '-' ? '−' : '+'}
            </div>
          )}
          <div style={{ fontSize: display.length > 9 ? 38 : display.length > 6 ? 50 : 64, fontWeight: 200, color: flash ? '#22c55e' : '#fff', letterSpacing: -2, lineHeight: 1, transition: 'color 0.2s', wordBreak: 'break-all' }}>
            {display}
          </div>
        </div>

        {/* Buttons */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {BTNS.map((row, ri) => (
            <div key={ri} style={{ display: 'grid', gridTemplateColumns: row.some(b => b.t === 'w') ? '2fr 1fr 1fr' : 'repeat(4, 1fr)', gap: 12 }}>
              {row.map((btn, bi) => (
                <button key={bi} onClick={btn.a}
                  style={{ height: 72, borderRadius: 36, background: getBg(btn.t, btn.l), color: getColor(btn.t, btn.l), fontSize: btn.t === 'fn' && btn.l.length > 1 ? 18 : 26, fontWeight: 400, border: 'none', cursor: 'pointer', transition: 'all 0.08s', display: 'flex', alignItems: 'center', justifyContent: btn.t === 'w' ? 'flex-start' : 'center', paddingLeft: btn.t === 'w' ? 28 : 0, userSelect: 'none' }}
                  onMouseDown={e => { e.currentTarget.style.opacity = '0.7'; e.currentTarget.style.transform = 'scale(0.94)' }}
                  onMouseUp={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.transform = 'scale(1)' }}
                  onMouseLeave={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.transform = 'scale(1)' }}
                  onTouchStart={e => { e.currentTarget.style.opacity = '0.7'; e.currentTarget.style.transform = 'scale(0.94)' }}
                  onTouchEnd={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.transform = 'scale(1)' }}>
                  {btn.l}
                </button>
              ))}
            </div>
          ))}
        </div>

        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <div style={{ width: 4, height: 4, borderRadius: '50%', background: 'rgba(255,255,255,0.06)', margin: '0 auto' }} />
        </div>
      </div>
    </div>
  )
}
