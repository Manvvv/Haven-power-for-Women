// frontend/src/locales/registry.ts
// ─────────────────────────────────────────────────────────────────────────────
// Central language registry for HAVEN. Single source of truth for every
// supported language's metadata. UI, i18n resolver, selector, validator and the
// backend contract all key off this list.
//
// Required shape (spec §2): { code, name, native_name, direction, script, fallback }
// Extra fields (`status`, `bcp47`) are additive and used for the honest coverage
// report + Intl locale-aware formatting. They never change fallback behaviour.
//
// HONESTY RULE (spec §2/§10): a language is only marked `first_class` when its
// core safety/UI strings are actually authored AND covered by tests. Everything
// else falls back to English at runtime rather than showing invented text.
// ─────────────────────────────────────────────────────────────────────────────

export type Lang =
  | 'en' | 'hi' | 'hinglish'
  | 'bn' | 'mr' | 'ta' | 'te' | 'gu' | 'kn' | 'ml' | 'pa' | 'or' | 'as'

export type Direction = 'ltr' | 'rtl'

/**
 * first_class  — safety + UI strings authored and tested (en, hi, hinglish).
 * community    — partial UI translations exist in-repo, NOT safety-reviewed.
 * fallback     — registered for selection; resolves to English until reviewed.
 */
export type LangStatus = 'first_class' | 'community' | 'fallback'

export interface LanguageMeta {
  code: Lang
  name: string          // English name
  native_name: string   // endonym, shown in the selector
  direction: Direction
  script: string
  fallback: Lang        // deterministic fallback target (always resolves to 'en')
  status: LangStatus
  bcp47: string         // for Intl date/number formatting (spec §17)
}

export const LANGUAGES: LanguageMeta[] = [
  { code: 'en',       name: 'English',   native_name: 'English',  direction: 'ltr', script: 'Latin',      fallback: 'en', status: 'first_class', bcp47: 'en-IN' },
  { code: 'hi',       name: 'Hindi',     native_name: 'हिन्दी',    direction: 'ltr', script: 'Devanagari', fallback: 'en', status: 'first_class', bcp47: 'hi-IN' },
  { code: 'hinglish', name: 'Hinglish',  native_name: 'Hinglish', direction: 'ltr', script: 'Latin',      fallback: 'en', status: 'first_class', bcp47: 'en-IN' },
  { code: 'bn',       name: 'Bengali',   native_name: 'বাংলা',     direction: 'ltr', script: 'Bengali',    fallback: 'en', status: 'community',   bcp47: 'bn-IN' },
  { code: 'mr',       name: 'Marathi',   native_name: 'मराठी',     direction: 'ltr', script: 'Devanagari', fallback: 'en', status: 'community',   bcp47: 'mr-IN' },
  { code: 'ta',       name: 'Tamil',     native_name: 'தமிழ்',     direction: 'ltr', script: 'Tamil',      fallback: 'en', status: 'community',   bcp47: 'ta-IN' },
  { code: 'te',       name: 'Telugu',    native_name: 'తెలుగు',    direction: 'ltr', script: 'Telugu',     fallback: 'en', status: 'community',   bcp47: 'te-IN' },
  { code: 'gu',       name: 'Gujarati',  native_name: 'ગુજરાતી',   direction: 'ltr', script: 'Gujarati',   fallback: 'en', status: 'community',   bcp47: 'gu-IN' },
  { code: 'kn',       name: 'Kannada',   native_name: 'ಕನ್ನಡ',     direction: 'ltr', script: 'Kannada',    fallback: 'en', status: 'fallback',    bcp47: 'kn-IN' },
  { code: 'ml',       name: 'Malayalam', native_name: 'മലയാളം',    direction: 'ltr', script: 'Malayalam',  fallback: 'en', status: 'fallback',    bcp47: 'ml-IN' },
  { code: 'pa',       name: 'Punjabi',   native_name: 'ਪੰਜਾਬੀ',    direction: 'ltr', script: 'Gurmukhi',   fallback: 'en', status: 'fallback',    bcp47: 'pa-IN' },
  { code: 'or',       name: 'Odia',      native_name: 'ଓଡ଼ିଆ',      direction: 'ltr', script: 'Odia',       fallback: 'en', status: 'fallback',    bcp47: 'or-IN' },
  { code: 'as',       name: 'Assamese',  native_name: 'অসমীয়া',    direction: 'ltr', script: 'Bengali',    fallback: 'en', status: 'fallback',    bcp47: 'as-IN' },
]

export const DEFAULT_LANG: Lang = 'en'

export const SUPPORTED_CODES: Lang[] = LANGUAGES.map(l => l.code)

const BY_CODE: Record<string, LanguageMeta> =
  Object.fromEntries(LANGUAGES.map(l => [l.code, l]))

export function isSupported(code: string | null | undefined): code is Lang {
  return !!code && code in BY_CODE
}

export function getLanguage(code: string | null | undefined): LanguageMeta {
  return (code && BY_CODE[code]) || BY_CODE[DEFAULT_LANG]
}

/** Deterministic fallback chain: requested → registry.fallback → … → 'en'. */
export function fallbackChain(code: Lang): Lang[] {
  const chain: Lang[] = []
  let cur: Lang | undefined = code
  const seen = new Set<Lang>()
  while (cur && !seen.has(cur)) {
    seen.add(cur)
    chain.push(cur)
    const meta: LanguageMeta | undefined = BY_CODE[cur]
    cur = meta && meta.fallback !== cur ? meta.fallback : undefined
  }
  if (!chain.includes(DEFAULT_LANG)) chain.push(DEFAULT_LANG)
  return chain
}

export function isFirstClass(code: Lang): boolean {
  return getLanguage(code).status === 'first_class'
}
