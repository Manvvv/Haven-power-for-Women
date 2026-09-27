# HAVEN — Localization Audit & Migration Plan

_Read-only audit completed before any code change (spec §1). Date: 2026-09-25._

## 1. Current architecture (as-is)

- **No i18n library.** `frontend/package.json` has no `next-intl` / `react-i18next` / `i18next` / `formatjs`. Localization is one bespoke React context: `frontend/src/components/LanguageContext.tsx`.
- **Single flat dictionary** `T: Record<key, Record<Lang, string>>` (~50 keys) covering nav/home/dashboard/sos/therapy/legal/footer/panic.
- **Languages (frontend):** `en, hi, gu, mr, te, bn, ta` (7). **No `hinglish`.** Missing spec langs `kn, ml, pa, or, as`.
- **Registry shape** is `{ code, name, native, flag }` — does NOT match required `{ code, name, native_name, direction, script, fallback }`.
- **Resolver** `t(key) = T[key]?.[lang] || T[key]?.['en'] || key` — 2-level fallback only.
- **Persistence** `localStorage['haven_lang']`; no auth/profile preference; no auto-detection; no dev missing-key warning; no lazy loading.
- **Selector** rendered on only 2 of ~11 routes (home, dashboard).

## 2. Backend language handling (as-is)

- **Two independent `detect_language`** implementations (mental_health_triage.py, legal_triage.py). Both support exactly `en / hi (Devanagari) / hinglish (romanized)`; everything else silently → `en`.
- **MH deterministic triage** covers en/hi/hinglish for suicide/self-harm/imminent/abuse/child/medical/dosing. The **fuzzy/semantic layer has no Devanagari anchors** (EN+Hinglish only).
- **Fixed crisis/med/AI-down text** exists only in en/hi/hinglish (`_pick_lang` falls back to en).
- **Legal**: corpus bodies are English; Hindi via keywords (26/39 entries); no Hinglish corpus keywords; all scaffolding text (clarifying Q / next steps / evidence / disclaimers) is English-only.
- **Voice SOS / SOS intent path is English-only** (`rule_classifier` + `preprocessing.tokenize` are ASCII/English). Hindi/Hinglish emergency speech is not recognized there.
- **Response language is a soft LLM instruction** (`"Reply in {lang}"`), never enforced. `ai_service.py` is language-agnostic.

## 3. Gaps found

- Hardcoded English across: `legal`, `sos`, `voice-sos`, `therapy/safety-plan`, `admin`, `authority`, `privacy` pages; `OfflineBanner`, `PanicButton`, `SOSLifecycle`, `SafetyPanels`, `therapy/support.ts` components.
- `home` bug: `t('signUp')` renders literal `"signUp"` (no such key).
- Defined-but-unused keys (therapy/legal pages hardcode English though translations exist in `T`).
- `<html lang="en">` static; page metadata English-only.
- Accessibility strings (aria-label/alt/title) hardcoded English everywhere.
- Second untranslated source: `therapy/support.ts` offline pack.

## 4. Migration plan (this change)

1. **Central registry** `locales/registry.ts` — 13 languages, required shape, helpers.
2. **i18n core** `locales/i18n.ts` — namespaced resolve, deterministic fallback chain (requested → registry.fallback → en), `{param}` interpolation, dev-only missing-key warning.
3. **Central namespaced strings** `locales/strings.ts` — namespaces: common, navigation, auth, sos, voice_sos, mental_health, legal, authority, admin, notifications, errors, accessibility, resources. Existing 7-language values preserved; `hinglish` authored; `en/hi/hinglish` = first-class.
4. **Rewrite `LanguageContext.tsx`** — extend `Lang` to 13, keep backward-compatible `t(key)` (existing pages keep working), add `tn(ns,key,params)`, expose `dir`/`script`/`meta`, auto-detection priority chain, auth-profile hook, `<html lang/dir>` sync.
5. **Upgrade selector** — all 13 native names.
6. **Validator** `backend/validate_localization.py` — missing/extra/empty keys, placeholder mismatches, critical safety strings, resource labels.
7. **Backend contract** — add `detected_language / response_language / supported_languages / fallback_used` to therapy + legal responses (non-breaking).
8. **Honesty rule (spec §2/§10):** regional languages without reviewed safety translations fall back to English; coverage report marks only tested cells PASS. No fabricated crisis/legal translations.
