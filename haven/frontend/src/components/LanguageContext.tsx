'use client'
// ─────────────────────────────────────────────────────────────────────────────
// HAVEN language context — now backed by the centralized locale modules
// (`locales/registry.ts`, `locales/i18n.ts`, `locales/strings.ts`).
//
// Backward compatibility is a hard requirement (spec §1 "migrate WITHOUT
// regressions"): every existing call site uses `const { t } = useLang()` with a
// bare key like `t('appName')`. That keeps working unchanged because `t` now
// delegates to `resolveFlat`, which looks a bare key up across all namespaces
// (legacy keys were preserved verbatim in `strings.ts`). New code should prefer
// the namespaced `tn('sos', 'sendAlert')` form.
// ─────────────────────────────────────────────────────────────────────────────
import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react'
import {
  Lang, LanguageMeta, LANGUAGES as REGISTRY, DEFAULT_LANG,
  getLanguage, isSupported,
} from '../locales/registry'
import { Namespace, resolve, resolveFlat } from '../locales/i18n'
import { STRINGS } from '../locales/strings'

export type { Lang } from '../locales/registry'

// Re-export for existing imports. Selector consumes the richer registry shape.
export const LANGUAGES = REGISTRY

const STORAGE_KEY = 'haven_lang'

// ── Auto-detection (spec §7) ─────────────────────────────────────────────────
// Priority: explicit saved choice → auth-profile → browser locale → English.
// Per-message code-switch detection is a backend concern and never overrides an
// explicit UI choice, so it is intentionally NOT part of provider init.
function detectInitialLang(authLang?: string | null): Lang {
  // 1. Explicit saved choice (also represents a prior manual selection).
  try {
    const saved = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
    if (isSupported(saved)) return saved
  } catch { /* localStorage may be unavailable (SSR / privacy mode) */ }

  // 2. Authenticated profile preference.
  if (isSupported(authLang)) return authLang

  // 3. Browser locale (best-effort, mapped to a supported base code).
  try {
    if (typeof navigator !== 'undefined' && navigator.language) {
      const base = navigator.language.toLowerCase().split('-')[0]
      if (isSupported(base)) return base
    }
  } catch { /* ignore */ }

  // 4. Deterministic final fallback.
  return DEFAULT_LANG
}

// ── Context ──────────────────────────────────────────────────────────────────
interface LangContextType {
  lang: Lang
  setLang: (l: Lang) => void
  /** Legacy flat resolver — `t('appName')`. Kept for backward compatibility. */
  t: (key: string, params?: Record<string, string | number>) => string
  /** Namespaced resolver — `tn('sos', 'sendAlert')`. Preferred for new code. */
  tn: (ns: Namespace, key: string, params?: Record<string, string | number>) => string
  dir: 'ltr' | 'rtl'
  script: string
  meta: LanguageMeta
}

const LangContext = createContext<LangContextType>({
  lang: DEFAULT_LANG,
  setLang: () => {},
  t: (key) => key,
  tn: (_ns, key) => key,
  dir: 'ltr',
  script: 'Latin',
  meta: getLanguage(DEFAULT_LANG),
})

export function LanguageProvider(
  { children, authLang }: { children: ReactNode; authLang?: string | null },
) {
  const [lang, setLangState] = useState<Lang>(DEFAULT_LANG)

  // Resolve the real initial language on the client (avoids SSR hydration flash:
  // server + first client render both use DEFAULT_LANG, then we upgrade once).
  useEffect(() => {
    setLangState(detectInitialLang(authLang))
  }, [authLang])

  // Keep <html lang/dir> in sync for a11y + correct text shaping (spec §17/§20).
  useEffect(() => {
    if (typeof document === 'undefined') return
    const meta = getLanguage(lang)
    document.documentElement.lang = meta.bcp47 || meta.code
    document.documentElement.dir = meta.direction
  }, [lang])

  const setLang = useCallback((l: Lang) => {
    if (!isSupported(l)) return
    setLangState(l)
    try { localStorage.setItem(STORAGE_KEY, l) } catch { /* ignore */ }
  }, [])

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) =>
      resolveFlat(STRINGS, lang, key, params),
    [lang],
  )

  const tn = useCallback(
    (ns: Namespace, key: string, params?: Record<string, string | number>) =>
      resolve(STRINGS, lang, ns, key, params),
    [lang],
  )

  const meta = getLanguage(lang)

  return (
    <LangContext.Provider
      value={{ lang, setLang, t, tn, dir: meta.direction, script: meta.script, meta }}
    >
      {children}
    </LangContext.Provider>
  )
}

export function useLang() {
  return useContext(LangContext)
}

// ── Language Selector Component ───────────────────────────────────────────────
// Shows every registered language by its NATIVE name (spec §6). Community /
// fallback-tier languages are marked so users know coverage is partial and text
// may appear in English — honest rather than pretending full translation.
export function LanguageSelector({ compact = false }: { compact?: boolean }) {
  const { lang, setLang, meta, tn } = useLang()
  const [open, setOpen] = useState(false)

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(v => !v)}
        aria-label={tn('accessibility', 'selectLanguage')}
        aria-expanded={open}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          background: 'rgba(190,24,93,0.08)',
          border: '1px solid rgba(190,24,93,0.2)',
          borderRadius: 20, padding: compact ? '5px 10px' : '6px 14px',
          cursor: 'pointer', fontSize: compact ? '0.72rem' : '0.78rem',
          color: '#be185d', fontWeight: 600, whiteSpace: 'nowrap',
        }}
      >
        <span aria-hidden>🌐</span>
        <span>{compact ? meta.code.toUpperCase() : meta.native_name}</span>
        <span style={{ fontSize: '0.6rem' }} aria-hidden>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div
          role="listbox"
          style={{
            position: 'absolute', top: '110%', right: 0,
            background: 'white', borderRadius: 14,
            border: '1px solid rgba(190,24,93,0.15)',
            boxShadow: '0 8px 32px rgba(190,24,93,0.15)',
            zIndex: 1000, minWidth: 180, maxHeight: 340, overflowY: 'auto',
          }}
        >
          {LANGUAGES.map(l => (
            <button
              key={l.code}
              role="option"
              aria-selected={lang === l.code}
              onClick={() => { setLang(l.code); setOpen(false) }}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                width: '100%', padding: '10px 16px',
                background: lang === l.code ? 'rgba(190,24,93,0.08)' : 'white',
                border: 'none', cursor: 'pointer', textAlign: 'left',
                fontSize: '0.82rem', color: lang === l.code ? '#be185d' : '#1a0a12',
                fontWeight: lang === l.code ? 700 : 400,
                borderBottom: '1px solid rgba(190,24,93,0.06)',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => { if (lang !== l.code) e.currentTarget.style.background = '#fdf2f8' }}
              onMouseLeave={e => { if (lang !== l.code) e.currentTarget.style.background = 'white' }}
            >
              <div>
                <div style={{ fontSize: '0.82rem' }}>{l.native_name}</div>
                <div style={{ fontSize: '0.65rem', color: '#8b6b7d' }}>
                  {l.name}{l.status !== 'first_class' ? ' · partial' : ''}
                </div>
              </div>
              {lang === l.code && <span style={{ marginLeft: 'auto', color: '#be185d' }}>✓</span>}
            </button>
          ))}
        </div>
      )}

      {open && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 999 }}
          onClick={() => setOpen(false)}
          aria-hidden
        />
      )}
    </div>
  )
}

// ── Helper: get AI language instruction (spec §9) ────────────────────────────
// Explicit, per-language response-language instruction for the LLM. Only the
// first-class languages get an authored native instruction; everything else
// resolves to a clear English directive naming the target language. This never
// fabricates translated content — it only tells the model which language to use.
const _AI_INSTRUCTIONS: Partial<Record<Lang, string>> = {
  en: 'Respond in English.',
  hi: 'हिंदी में उत्तर दें। (Respond only in Hindi, using Devanagari script.)',
  hinglish:
    'Reply in Hinglish — conversational Hindi written in the Latin/Roman script (e.g. "Aap theek ho? Main aapke saath hoon."). Do not use Devanagari.',
}

export function getAILanguageInstruction(lang: Lang): string {
  if (_AI_INSTRUCTIONS[lang]) return _AI_INSTRUCTIONS[lang] as string
  const meta = getLanguage(lang)
  return `Respond in ${meta.name} (${meta.native_name}).`
}
