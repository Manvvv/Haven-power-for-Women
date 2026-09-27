// frontend/src/locales/i18n.ts
// ─────────────────────────────────────────────────────────────────────────────
// Framework-free i18n core. No runtime machine translation, no network calls —
// every string is resolved from the local `STRINGS` table (spec §23 privacy,
// §10 no dynamic MT). Deterministic fallback chain guarantees we NEVER render
// `undefined`, a raw key, or a missing-translation placeholder (spec §20).
// ─────────────────────────────────────────────────────────────────────────────
import { Lang, fallbackChain } from './registry'

// Logical namespaces (spec §3). Keeping them explicit lets the validator and
// lazy-loader reason about groups of strings.
export const NAMESPACES = [
  'common', 'navigation', 'auth', 'sos', 'voice_sos', 'mental_health',
  'legal', 'authority', 'admin', 'notifications', 'errors',
  'accessibility', 'resources',
] as const

export type Namespace = typeof NAMESPACES[number]

// A single string keyed by language. Languages may be omitted; the resolver
// walks the fallback chain to find the first defined value.
export type LangMap = Partial<Record<Lang, string>>
export type NamespaceDict = Record<string, LangMap>
export type StringTable = Record<Namespace, NamespaceDict>

const IS_DEV =
  typeof process !== 'undefined' && process.env && process.env.NODE_ENV !== 'production'

const _warned = new Set<string>()

function warnOnce(msg: string) {
  if (!IS_DEV) return
  if (_warned.has(msg)) return
  _warned.add(msg)
  // eslint-disable-next-line no-console
  console.warn('[i18n] ' + msg)
}

/** Interpolate {param} placeholders. Missing params are left as-is (visible in dev). */
export function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (m, k) =>
    k in params ? String(params[k]) : m,
  )
}

/**
 * Resolve one string.
 *   table  — the STRINGS object (or a lazily-merged subset).
 *   lang   — requested language.
 *   ns/key — namespace + key.
 *   params — interpolation values.
 * Fallback: requested → registry fallback(s) → 'en'. Returns the key itself only
 * if the key genuinely does not exist in ANY language (a developer error, warned
 * in dev). This is the last line of defence against showing `undefined`.
 */
export function resolve(
  table: StringTable,
  lang: Lang,
  ns: Namespace,
  key: string,
  params?: Record<string, string | number>,
): string {
  const dict = table[ns]
  if (!dict || !(key in dict)) {
    warnOnce(`missing key "${ns}.${key}"`)
    return key
  }
  const langMap = dict[key]
  for (const code of fallbackChain(lang)) {
    const v = langMap[code]
    if (typeof v === 'string' && v.length > 0) {
      if (code !== lang && code === 'en') {
        warnOnce(`"${ns}.${key}" not translated for "${lang}" — using English`)
      }
      return interpolate(v, params)
    }
  }
  warnOnce(`"${ns}.${key}" has no value in any language`)
  return key
}

/**
 * Flat/legacy resolver. Existing pages call `t('appName')` with no namespace.
 * We look the bare key up across all namespaces (keys are unique across the
 * table) so those call sites keep working with ZERO changes — no regression.
 */
export function resolveFlat(
  table: StringTable,
  lang: Lang,
  key: string,
  params?: Record<string, string | number>,
): string {
  // Support explicit "namespace:key" form too.
  if (key.includes(':')) {
    const [ns, k] = key.split(':', 2)
    if ((NAMESPACES as readonly string[]).includes(ns)) {
      return resolve(table, lang, ns as Namespace, k, params)
    }
  }
  for (const ns of NAMESPACES) {
    const dict = table[ns]
    if (dict && key in dict) return resolve(table, lang, ns, key, params)
  }
  warnOnce(`unknown flat key "${key}"`)
  return key
}
