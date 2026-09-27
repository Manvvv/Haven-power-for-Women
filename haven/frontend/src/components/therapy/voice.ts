// ─────────────────────────────────────────────────────────────────────────────
// Aria voice selection — pure, framework-free helpers for the browser Web Speech
// API. Kept OUT of the page component so Next's App Router export constraints
// don't apply and so the selection logic can be unit-tested without a real
// SpeechSynthesis engine. Presentation only: this never touches Aria's wording
// or any mental-health safety logic.
// ─────────────────────────────────────────────────────────────────────────────

// Per-language BCP-47 code preference + a female-name hint for that locale.
// `hinglish` (and any unmapped language) falls through to `en`, whose codes
// lead with `en-IN` — the right choice for Indian-English / Hinglish speech.
export const LANG_VOICE_MAP: Record<string, { codes: string[]; keywords: RegExp }> = {
  en: { codes: ['en-IN', 'en-US', 'en-GB', 'en'], keywords: /samantha|karen|victoria|aria|zira|female/i },
  hi: { codes: ['hi-IN', 'hi_IN', 'hi'], keywords: /hindi|हिन्दी|lekha|swara|kalpana|neerja|heera|female/i },
  gu: { codes: ['gu-IN', 'gu_IN', 'gu', 'hi-IN'], keywords: /gujarati|ગુજરાતી|dhwani|female/i },
  mr: { codes: ['mr-IN', 'mr_IN', 'mr', 'hi-IN'], keywords: /marathi|मराठी|aarohi|female/i },
  te: { codes: ['te-IN', 'te_IN', 'te', 'hi-IN'], keywords: /telugu|తెలుగు|chitra|female/i },
  bn: { codes: ['bn-IN', 'bn_IN', 'bn', 'hi-IN'], keywords: /bengali|bangla|বাংলা|tanisha|female/i },
  ta: { codes: ['ta-IN', 'ta_IN', 'ta', 'hi-IN'], keywords: /tamil|தமிழ்|female/i },
}

// Known FEMALE TTS voice names across Windows (SAPI/Edge), macOS/iOS and
// Android/Chrome. Matching `\bfemale\b` explicitly means the shared token
// "male" inside "female" never trips the male denylist below.
export const FEMALE_VOICE =
  /\bfemale\b|zira|heera|kalpana|swara|neerja|aarohi|dhwani|chitra|tanisha|lekha|veena|raveena|aditi|priya|ananya|samantha|karen|victoria|moira|tessa|fiona|serena|allison|ava|susan|zoe|joana|catherine|hazel|linda|google (uk|us) english female|google हिन्दी/i

// Known MALE TTS voice names to actively AVOID. `\bmale\b` cannot match inside
// "female" (the 'm' is preceded by a word char, so there is no word boundary),
// so a voice literally named "…Female" is never mistaken for male.
export const MALE_VOICE =
  /\bmale\b|david|mark|george|guy|james|ryan|eric|roger|hemant|madhur|prabhat|ravi|rishi|daniel|thomas|oliver|alex|fred|gordon|aaron|arthur|william|paul|liam/i

/**
 * Deterministically choose a warm FEMALE voice for `lang`, independent of the
 * order the OS happens to return `voices` in. Preference order (each step falls
 * through only if empty):
 *   1. Female voice per PREFERRED BCP-47 CODE, walked in `cfg.codes` order.
 *      For en / Hinglish `cfg.codes` is [en-IN, en-US, en-GB, en], so this
 *      resolves, in order: female en-IN → female en-US → female en-GB →
 *      any other female English (en-*). For Hindi it's female hi-IN → hi.
 *      This is the fix for "OS ordering could pick either en-IN or en-US".
 *   2. Any other clearly-female English voice (e.g. en-AU / en-CA female).
 *   3. Any clearly-female, language-compatible voice, any locale.
 *   4. Existing safe fallback: a non-male voice in the target language →
 *      any voice in the target language → any non-male voice →
 *      first available voice (last resort only).
 * It never STARTS from `voices[0]`, so a male language-default cannot win, and
 * the female-name filtering (FEMALE_VOICE / cfg.keywords) is preserved.
 * Returns null only when the browser exposes no voices at all.
 */
export function pickVoice(
  voices: SpeechSynthesisVoice[],
  lang: string,
): SpeechSynthesisVoice | null {
  if (!voices || voices.length === 0) return null
  const cfg = LANG_VOICE_MAP[lang] || LANG_VOICE_MAP['en']
  const norm = (s: string) => s.toLowerCase().replace(/_/g, '-')
  const startsWith = (v: SpeechSynthesisVoice, code: string) =>
    norm(v.lang).startsWith(norm(code))
  const inLang = (v: SpeechSynthesisVoice) => cfg.codes.some(code => startsWith(v, code))
  const female = (v: SpeechSynthesisVoice) =>
    FEMALE_VOICE.test(v.name) || cfg.keywords.test(v.name)
  const male = (v: SpeechSynthesisVoice) => MALE_VOICE.test(v.name)
  const isEnglish = (v: SpeechSynthesisVoice) => norm(v.lang).startsWith('en')

  // 1) Female, non-male voice per preferred code, tried in cfg.codes order.
  //    Walking the codes (not the raw voice array) makes en-IN beat en-US
  //    beat en-GB deterministically, regardless of OS voice ordering.
  for (const code of cfg.codes) {
    const hit = voices.find(v => startsWith(v, code) && female(v) && !male(v))
    if (hit) return hit
  }

  return (
    // 2) Any other female English voice (covers en-AU/en-CA/… for Hinglish).
    voices.find(v => female(v) && !male(v) && isEnglish(v)) ||
    // 3) Any clearly-female, language-compatible voice, any locale.
    voices.find(v => female(v) && !male(v)) ||
    // 4) Existing safe fallback — never a male if avoidable; voices[0] last.
    voices.find(v => inLang(v) && !male(v)) ||
    voices.find(v => inLang(v)) ||
    voices.find(v => !male(v)) ||
    voices[0]
  )
}

/** Lead BCP-47 code for a language, used as the utterance's fallback `lang`. */
export function leadLangCode(lang: string): string {
  return (LANG_VOICE_MAP[lang] || LANG_VOICE_MAP['en']).codes[0] || 'en-US'
}
