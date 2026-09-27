// Shared parsing for timestamps that come FROM THE BACKEND.
//
// The Python backend stores/returns times via `datetime.utcnow().isoformat()`
// (e.g. sos_routes.py, audit trail, DIR generation). That produces a *naive*
// ISO-8601 string with NO timezone designator, e.g. "2026-09-27T14:26:18.123".
//
// JavaScript's `new Date(str)` interprets a date-*time* string that has no
// zone as the viewer's LOCAL time (per the ES spec). So in an IST browser a
// 14:26 UTC event is read as 14:26 IST, and any subsequent formatting — even
// `Intl.DateTimeFormat({ timeZone: 'Asia/Kolkata' })` — shows it 5h30m behind
// the real IST wall-clock. (Date-ONLY strings like "2026-09-27" are already
// spec'd to parse as UTC, so those are left untouched.)
//
// `parseServerDate` normalizes by appending 'Z' to a zone-less date-time so it
// is correctly read as UTC. Strings that already carry a zone (trailing 'Z' or
// a ±HH:MM offset), Date instances, and epoch numbers pass through unchanged.
// This is a *display-parse* fix only — it never mutates stored data.

export function parseServerDate(
  value: string | number | Date | null | undefined
): Date | null {
  if (value == null) return null

  if (value instanceof Date) {
    return isNaN(value.getTime()) ? null : value
  }

  if (typeof value === 'number') {
    const d = new Date(value)
    return isNaN(d.getTime()) ? null : d
  }

  const s = String(value).trim()
  if (!s) return null

  // Already zone-qualified? (…Z  or  …+05:30 / …-0800)
  const hasZone = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(s)
  // Does it carry a time component (so local-vs-UTC actually matters)?
  const hasTime = /\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s)

  const normalized = hasTime && !hasZone ? s.replace(' ', 'T') + 'Z' : s
  const d = new Date(normalized)
  return isNaN(d.getTime()) ? null : d
}

// Convenience: safe `toLocaleString()` for a backend timestamp. Returns the
// given fallback (default '') when the value is missing/unparseable, so call
// sites don't each repeat the guard.
export function formatServerDateTime(
  value: string | number | Date | null | undefined,
  fallback = ''
): string {
  const d = parseServerDate(value)
  return d ? d.toLocaleString() : fallback
}
