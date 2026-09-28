// frontend/src/lib/greeting.ts
// ─────────────────────────────────────────────────────────────────────────────
// Pure, framework-free helper for deriving the dashboard greeting name from the
// AUTHENTICATED identity only. Extracted so it can be unit-tested without a
// browser/Clerk runtime (mirrors the therapy `voice.ts` pattern).
//
// Contract (issue: dashboard showed a hardcoded "Manav"):
//   • Prefer a proper display name (Clerk `fullName`).
//   • Else the first name (`firstName`).
//   • Else a safe, generic fallback (e.g. "there") — NEVER a hardcoded person's
//     name and NEVER another user's name.
//   • Until the auth session has hydrated (`isLoaded === false`) we return the
//     fallback, so the wrong name can never flash before the real identity
//     resolves. The caller supplies a localized fallback string.
//
// This helper deliberately does NOT trust any client-supplied name for
// authorization; it only decides what to DISPLAY. Identity/authorization is
// always derived server-side from the verified token.
// ─────────────────────────────────────────────────────────────────────────────

/** Minimal duck-typed view of the fields we read off a Clerk user. */
export interface GreetingUser {
  fullName?: string | null
  firstName?: string | null
}

/**
 * Resolve the name to greet.
 *   user     — the authenticated user (or null/undefined before hydration).
 *   isLoaded — whether the auth session has finished loading.
 *   fallback — localized generic fallback (defaults to "there").
 */
export function resolveGreetingName(
  user: GreetingUser | null | undefined,
  isLoaded: boolean,
  fallback = 'there',
): string {
  if (!isLoaded || !user) return fallback
  const full = (user.fullName || '').trim()
  if (full) return full
  const first = (user.firstName || '').trim()
  if (first) return first
  return fallback
}
