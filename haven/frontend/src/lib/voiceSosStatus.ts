/**
 * Pure, framework-free Voice-SOS lifecycle helpers.
 *
 * The Voice-SOS page runs a browser SpeechRecognition loop whose visible state
 * must never "silently fail": the user always sees whether the app is idle,
 * listening, processing a detected safe word, has just sent an SOS, is cooling
 * down, was denied the microphone, is unsupported, or errored. Deriving that
 * single status from the raw signals is extracted here so it can be unit-tested
 * without a browser or React, and reused by any surface that shows Voice-SOS
 * state.
 *
 * NOTE: messages here are deliberately generic and NEVER embed the recognized
 * transcript — recognition text must not leak into UI error strings or logs.
 */

export type VoiceSosStatus =
  | 'unsupported'
  | 'processing'
  | 'triggered'
  | 'cooldown'
  | 'permission_denied'
  | 'failed'
  | 'listening'
  | 'idle'

/** The trigger lifecycle phase, owned by the page and fed into the derivation. */
export type TriggerPhase = 'idle' | 'processing' | 'sent' | 'cooldown'

export interface VoiceStatusInputs {
  /** null = not yet probed; false = no SpeechRecognition in this browser. */
  isSupported: boolean | null
  micPermission: 'granted' | 'denied' | 'pending'
  triggerPhase: TriggerPhase
  isListening: boolean
  /** A surfaced (non-benign) recognition/trigger error is outstanding. */
  hasError: boolean
}

/**
 * Collapse the raw signals into ONE status. Order encodes precedence:
 * a browser with no API can do nothing (`unsupported`); an in-flight or
 * just-sent SOS is the most important thing to show; a blocked mic prevents
 * listening; a surfaced error beats the quiet `listening`/`idle` states.
 */
export function deriveVoiceStatus(i: VoiceStatusInputs): VoiceSosStatus {
  if (i.isSupported === false) return 'unsupported'
  if (i.triggerPhase === 'processing') return 'processing'
  if (i.triggerPhase === 'sent') return 'triggered'
  if (i.triggerPhase === 'cooldown') return 'cooldown'
  if (i.micPermission === 'denied') return 'permission_denied'
  if (i.hasError) return 'failed'
  if (i.isListening) return 'listening'
  return 'idle'
}

export type StatusTone = 'danger' | 'success' | 'warning' | 'info' | 'muted'

export interface StatusMeta { label: string; tone: StatusTone; live: boolean }

/** Presentation metadata per status (English defaults; page may localize). */
export const VOICE_STATUS_META: Record<VoiceSosStatus, StatusMeta> = {
  unsupported:       { label: 'Not supported on this browser', tone: 'warning', live: false },
  permission_denied: { label: 'Microphone blocked',            tone: 'danger',  live: false },
  processing:        { label: 'Sending SOS…',                  tone: 'danger',  live: true  },
  triggered:         { label: 'SOS sent',                      tone: 'success', live: true  },
  cooldown:          { label: 'Cooldown — SOS just sent',      tone: 'warning', live: false },
  failed:            { label: 'Something went wrong',          tone: 'danger',  live: false },
  listening:         { label: 'Listening for your safe word',  tone: 'info',    live: true  },
  idle:              { label: 'Ready',                         tone: 'muted',   live: false },
}

export interface RecognitionErrorInfo {
  /** Caller should mark the mic denied and stop the auto-restart loop. */
  permissionDenied: boolean
  /** Transient/expected (no-speech, aborted) — do not alarm the user. */
  benign: boolean
  /** Retrying will not recover it (permission / no device). */
  fatal: boolean
  /** User-facing text — NEVER contains the recognized transcript. */
  message: string
}

/**
 * Map a SpeechRecognition `error` code to a user-facing outcome so that every
 * failure is either shown clearly or knowingly treated as benign — never
 * swallowed. The transcript is never included in the message.
 */
export function mapRecognitionError(code: string): RecognitionErrorInfo {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return { permissionDenied: true, benign: false, fatal: true,
               message: 'Microphone access is blocked. Enable mic permission for this site, then try again.' }
    case 'no-speech':
      return { permissionDenied: false, benign: true, fatal: false,
               message: 'No speech detected — still listening.' }
    case 'aborted':
      return { permissionDenied: false, benign: true, fatal: false,
               message: 'Listening was interrupted — restarting.' }
    case 'audio-capture':
      return { permissionDenied: false, benign: false, fatal: true,
               message: 'No microphone was found. Check your device and try again.' }
    case 'network':
      return { permissionDenied: false, benign: false, fatal: false,
               message: 'Speech recognition lost its network connection — retrying.' }
    default:
      return { permissionDenied: false, benign: false, fatal: false,
               message: `Voice recognition hit an error (${code || 'unknown'}) — retrying.` }
  }
}

