import React from 'react'
import { Check } from 'lucide-react'

interface StateHistory {
  status: string
  timestamp: string
  actor?: string
}

interface Props {
  currentStatus: string
  statusHistory: StateHistory[]
}

// Canonical backend lifecycle values — DO NOT change order or values.
const ALL_STATES = ['CREATED', 'ENCODED', 'SHARED', 'RECEIVED', 'DECODED', 'AI_ANALYZED', 'ACKNOWLEDGED', 'IN_PROGRESS', 'RESOLVED']

// Presentation-only labels. This is the SINGLE place canonical statuses are
// mapped to human-readable text; the raw canonical value is still used for
// logic and for the a11y announcement. Never send these back to the backend.
const STATE_LABELS: Record<string, string> = {
  CREATED: 'Created',
  ENCODED: 'Encoded',
  SHARED: 'Shared',
  RECEIVED: 'Received',
  DECODED: 'Decoded',
  AI_ANALYZED: 'AI Analyzed',
  ACKNOWLEDGED: 'Acknowledged',
  IN_PROGRESS: 'In Progress',
  RESOLVED: 'Resolved',
}

const GREEN = '#10b981'
const PINK = '#be185d'
const INACTIVE = '#e5e7eb'
// Per-step minimum width. Keeps the widest single-word label ("Acknowledged")
// on one line and lets two-word labels wrap at their space, so nothing collides.
// Below the resulting track width the container scrolls horizontally instead.
const MIN_STEP_PX = 92

export default function SOSLifecycle({ currentStatus, statusHistory }: Props) {
  const currentIndex = ALL_STATES.indexOf(currentStatus)
  const lastIndex = ALL_STATES.length - 1

  return (
    <div
      style={{
        width: '100%',
        overflowX: 'auto',
        WebkitOverflowScrolling: 'touch',
        padding: '1rem 0',
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      <ol
        aria-label="Case lifecycle timeline"
        style={{
          listStyle: 'none',
          margin: 0,
          padding: 0,
          display: 'grid',
          gridTemplateColumns: `repeat(${ALL_STATES.length}, minmax(0, 1fr))`,
          alignItems: 'start',
          minWidth: `${ALL_STATES.length * MIN_STEP_PX}px`,
        }}
      >
        {ALL_STATES.map((state, index) => {
          const isCompleted = index < currentIndex
          const isCurrent = index === currentIndex
          const isResolved = isCurrent && state === 'RESOLVED'
          const historyItem = statusHistory.find(h => h.status === state)
          const timeStr = historyItem
            ? new Date(historyItem.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            : null

          // Connector half-lines. The left half of a step is green once the step
          // is reached (index <= current); the right half once the step is passed
          // (index < current). Circle centering is unaffected by label width.
          const leftLineColor = index <= currentIndex && currentIndex >= 0 ? GREEN : INACTIVE
          const rightLineColor = index < currentIndex ? GREEN : INACTIVE

          const circleBg = isCompleted || isResolved ? GREEN : isCurrent ? PINK : INACTIVE
          const circleFg = isCompleted || isCurrent ? '#fff' : '#9ca3af'

          const stateWord = isResolved
            ? 'resolved, final step'
            : isCompleted
            ? 'completed'
            : isCurrent
            ? 'current step'
            : 'not yet reached'
          const ariaLabel = `Lifecycle status: ${state}, ${stateWord}${timeStr ? ` at ${timeStr}` : ''}`

          return (
            <li
              key={state}
              aria-label={ariaLabel}
              aria-current={isCurrent ? 'step' : undefined}
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 0 }}
            >
              {/* Circle + connector row. Purely decorative; the <li> aria-label
                  carries the meaning for assistive tech. */}
              <div
                aria-hidden="true"
                style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', width: '100%' }}
              >
                <span style={{ height: '2px', background: leftLineColor, visibility: index === 0 ? 'hidden' : 'visible' }} />
                <span
                  style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    flexShrink: 0,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    background: circleBg,
                    color: circleFg,
                    boxShadow: isCurrent && !isResolved ? `0 0 0 4px rgba(190,24,93,0.2)` : 'none',
                  }}
                >
                  {isCompleted || isResolved ? <Check size={16} /> : index + 1}
                </span>
                <span style={{ height: '2px', background: rightLineColor, visibility: index === lastIndex ? 'hidden' : 'visible' }} />
              </div>

              {/* Centered, wrapping label — no white-space: nowrap. */}
              <span
                style={{
                  marginTop: '0.5rem',
                  textAlign: 'center',
                  fontSize: '0.8rem',
                  lineHeight: 1.25,
                  fontWeight: isCurrent ? 700 : 500,
                  color: isCurrent ? '#1a0a12' : '#8b6b7d',
                  overflowWrap: 'break-word',
                  maxWidth: '100%',
                  padding: '0 2px',
                }}
              >
                {STATE_LABELS[state] || state}
              </span>

              {timeStr && (
                <time
                  dateTime={historyItem!.timestamp}
                  style={{ fontSize: '0.68rem', color: '#8b6b7d', marginTop: '0.2rem', textAlign: 'center' }}
                >
                  {timeStr}
                </time>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
