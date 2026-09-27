import React from 'react'
import { Check, Clock, ShieldAlert, ArrowRight, CheckCircle2 } from 'lucide-react'

interface StateHistory {
  status: string
  timestamp: string
  actor?: string
}

interface Props {
  currentStatus: string
  statusHistory: StateHistory[]
}

const ALL_STATES = ['CREATED', 'ENCODED', 'SHARED', 'RECEIVED', 'DECODED', 'AI_ANALYZED', 'ACKNOWLEDGED', 'IN_PROGRESS', 'RESOLVED']

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

export default function SOSLifecycle({ currentStatus, statusHistory }: Props) {
  const currentIndex = ALL_STATES.indexOf(currentStatus)

  return (
    <div style={{ padding: '1rem 0', fontFamily: 'system-ui, sans-serif', width: '100%', overflowX: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', minWidth: '600px' }}>
        {ALL_STATES.map((state, index) => {
          const isCompleted = index < currentIndex
          const isCurrent = index === currentIndex
          const historyItem = statusHistory.find(h => h.status === state)

          return (
            <React.Fragment key={state}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, position: 'relative' }}>
                <div style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  background: isCompleted ? '#10b981' : isCurrent ? '#be185d' : '#e5e7eb',
                  color: (isCompleted || isCurrent) ? '#fff' : '#9ca3af',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 2,
                  boxShadow: isCurrent ? '0 0 0 4px rgba(190,24,93,0.2)' : 'none'
                }}>
                  {isCompleted ? <Check size={16} /> : index + 1}
                </div>
                <div style={{
                  marginTop: '0.5rem',
                  fontWeight: isCurrent ? 'bold' : 'normal',
                  color: isCurrent ? '#1a0a12' : '#8b6b7d',
                  fontSize: '0.85rem',
                  textTransform: 'capitalize'
                }}>
                  {state}
                </div>
                {historyItem && (
                  <div style={{ fontSize: '0.7rem', color: '#8b6b7d', marginTop: '0.2rem' }}>
                    {new Date(historyItem.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                )}
              </div>
              {index < ALL_STATES.length - 1 && (
                <div style={{
                  flex: 1,
                  height: '2px',
                  background: index < currentIndex ? '#10b981' : '#e5e7eb',
                  margin: '0 -16px',
                  zIndex: 1,
                  transform: 'translateY(-16px)'
                }} />
              )}
            </React.Fragment>
          )
        })}
      </div>
    </div>
  )
}
