/**
 * support.ts — shared types + a SINGLE offline fallback pack for HAVEN's
 * mental-health module (spec §4, §24, §29, §34).
 *
 * Safety notes:
 *  - Verified helpline numbers are DATA. At runtime the UI reads them from the
 *    backend registry (`GET /therapy/resources`) so there is ONE source of truth.
 *  - The constants below are ONLY an offline / AI-unavailable fallback (spec §24,
 *    §29). They mirror `mental_health_resources.offline_pack()` so the crisis
 *    panel, grounding and breathing still work with no network. They live in this
 *    one module so no number is hardcoded across multiple components (spec §4).
 *  - Nothing here dials, notifies, or contacts anyone. Every action is an explicit
 *    user tap (a `tel:` link the user chooses to place, or a link to HAVEN SOS).
 */

// ── Structured /therapy/chat response (mirrors MentalHealthChatResponse) ──
export interface Resource {
  id?: string
  name?: string
  provider_name?: string
  type?: string
  number?: string
  alt_number?: string
  phone?: string
  purpose?: string
  specialty?: string
  country?: string
  state?: string
  city?: string
  source_url?: string
  official_url?: string
  authority_level?: string // "government_verified" | "ngo_helpline"
  verified_at?: string
  language_support?: string[]
  languages?: string[]
  availability?: string
}

export interface CopingTool {
  id: string
  title: string
  category?: string
  type?: string // always "support_strategy" from the backend
  steps: string[]
}

export interface Source {
  name?: string
  source_url?: string
  verified_at?: string
}

export interface ChatResponse {
  response: string
  risk_level: string
  crisis: boolean
  needs_clarification?: boolean
  clarifying_question?: string | null
  coping_tools?: CopingTool[]
  emergency_resources?: Resource[]
  professional_resources?: Resource[]
  safety_plan?: Record<string, unknown> | null
  language?: string
  sources?: Source[]
  disclaimer?: string | null
  session_id?: string | null
  mode?: string // "normal" | "moderate" | "crisis" | "emergency"
  ai_available?: boolean
  saved?: boolean
}

// ── Offline fallback (single source; mirrors backend offline_pack) ──
export const OFFLINE_EMERGENCY: Resource[] = [
  {
    id: 'emergency_112',
    name: 'National Emergency Number (ERSS)',
    type: 'emergency',
    number: '112',
    purpose: 'Immediate police, fire or medical emergency — pan-India response.',
    authority_level: 'government_verified',
    source_url: 'https://112.gov.in/',
    availability: '24x7',
  },
  {
    id: 'telemanas_14416',
    name: 'Tele-MANAS (National Tele Mental Health Programme)',
    type: 'mental_health_crisis',
    number: '14416',
    alt_number: '1800-891-4416',
    purpose:
      'Free, confidential 24x7 mental-health support and counselling by trained professionals.',
    authority_level: 'government_verified',
    source_url: 'https://telemanas.mohfw.gov.in/',
    availability: '24x7',
  },
]

export const OFFLINE_GROUNDING = {
  title: '5-4-3-2-1 grounding',
  steps: [
    'Name 5 things you can see.',
    'Name 4 things you can feel or touch.',
    'Name 3 things you can hear.',
    'Name 2 things you can smell.',
    'Name 1 thing you can taste, or take one slow breath.',
  ],
}

export const OFFLINE_BREATHING = {
  title: 'Slow breathing',
  steps: [
    'Breathe in gently through your nose for 4 counts.',
    'Hold for 4 counts.',
    'Breathe out slowly for 6 counts.',
    'Repeat a few times. Stop if you feel light-headed.',
  ],
}

export const OFFLINE_EMERGENCY_INSTRUCTIONS = [
  'If you or someone else is in immediate danger, call 112 now.',
  'Try to be with another person, or move to a place where you feel safer.',
  'Tele-MANAS (14416) has trained counsellors available 24x7.',
]

export const DISCLAIMER =
  'HAVEN offers emotional support and information, and is not a doctor, therapist, ' +
  'or emergency service. It cannot diagnose conditions or prescribe treatment. ' +
  'In an emergency, contact 112 or the resources below.'

// ── Helpers ──
/** Return a dialable form of a number for a `tel:` href (digits + leading +). */
export function telHref(num?: string): string {
  if (!num) return ''
  const cleaned = num.replace(/[^\d+]/g, '')
  return cleaned ? `tel:${cleaned}` : ''
}

/** Best display number for a resource (registry `number`/`alt_number` or `phone`). */
export function displayNumber(r: Resource): string {
  return r.number || r.phone || ''
}

/** Human label distinguishing government-verified lines from NGO-run lines (spec §4). */
export function authorityLabel(level?: string): { text: string; gov: boolean } {
  if (level === 'government_verified') return { text: 'Government verified', gov: true }
  if (level === 'ngo_helpline') return { text: 'NGO helpline', gov: false }
  return { text: '', gov: false }
}
