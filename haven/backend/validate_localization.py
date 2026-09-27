"""
validate_localization.py — dependency-free validator for HAVEN's centralized
localization layer (spec §21).

Parses the TypeScript source of truth directly (no Node / ts / npm needed):
  * frontend/src/locales/registry.ts   → supported languages + status tiers
  * frontend/src/locales/strings.ts     → the namespaced STRINGS table
  * frontend/src/locales/i18n.ts        → declared NAMESPACES

It checks, WITHOUT contacting any network or translation service:
  1. Every namespace declared in i18n.ts exists in STRINGS (and vice-versa).
  2. No empty namespaces and no empty string values.
  3. First-class languages (en, hi, hinglish) cover EVERY key — the honesty
     rule: we only claim a language is supported when it is actually authored.
  4. English (the deterministic final fallback) is present for every key, so the
     resolver can never return a raw key / undefined to a user (spec §20).
  5. {param} placeholders match across languages for the same key (a translation
     must not drop or invent an interpolation slot).
  6. Critical safety strings exist and carry the verified emergency numbers
     (112, 14416) verbatim — never machine-translated, never altered.
  7. No language is referenced in STRINGS that isn't registered in registry.ts.

Exit code 0 = all pass, 1 = failures. Run:  python3 validate_localization.py
(cwd = backend). Paths resolve relative to this file, so it also works from CI.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_LOCALES = os.path.normpath(os.path.join(_HERE, "..", "frontend", "src", "locales"))

FIRST_CLASS = ("en", "hi", "hinglish")
# Emergency identifiers that must survive verbatim in every language they appear
# in (spec §13/§16 — numbers/URLs are NOT translated).
VERIFIED_NUMBERS = ("112", "14416")

_FAILS = []
_PASSES = 0


def check(cond, label):
    global _PASSES
    if cond:
        _PASSES += 1
    else:
        _FAILS.append(label)


# ── Minimal, quote-aware TS object reader ────────────────────────────────────
def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(src):
    """Remove // line and /* */ block comments, but never inside string literals."""
    out = []
    i = 0
    n = len(src)
    quote = None
    esc = False
    while i < n:
        c = src[i]
        if quote:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            quote = c
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)



def _match_brace(src, i):
    """Given src[i] == '{', return index just past the matching '}'. Quote-aware."""
    depth = 0
    quote = None
    esc = False
    while i < len(src):
        c = src[i]
        if quote:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
        else:
            if c in ("'", '"', "`"):
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    raise ValueError("unbalanced braces")


_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")


def _parse_object(body):
    """Parse a `{ key: <value>, ... }` body one level deep.

    Returns a list of (key, value_str) where value_str is the raw source of the
    value (either a `{...}` block or a quoted string), preserving order.
    """
    out = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c.isspace() or c == ",":
            i += 1
            continue
        if c == "}":
            break
        m = _IDENT_RE.match(body, i)
        if not m:
            i += 1
            continue
        key = m.group(0)
        j = m.end()
        while j < n and body[j] != ":":
            j += 1
        j += 1  # past ':'
        while j < n and body[j].isspace():
            j += 1
        if j >= n:
            break
        if body[j] == "{":
            end = _match_brace(body, j)
            out.append((key, body[j:end]))
            i = end
        elif body[j] in ("'", '"', "`"):
            q = body[j]
            k = j + 1
            esc = False
            while k < n:
                if esc:
                    esc = False
                elif body[k] == "\\":
                    esc = True
                elif body[k] == q:
                    break
                k += 1
            out.append((key, body[j:k + 1]))
            i = k + 1
        else:
            # scalar (identifier / number) — skip to next comma/brace
            k = j
            while k < n and body[k] not in (",", "}"):
                k += 1
            out.append((key, body[j:k].strip()))
            i = k
    return out


def _unquote(s):
    if s and s[0] in ("'", '"', "`"):
        inner = s[1:-1]
        return inner.replace("\\'", "'").replace('\\"', '"').replace("\\`", "`").replace("\\\\", "\\")
    return s


def _extract_named_object(src, name):
    """Find `... {name} ... = {` and return the body inside the outer braces."""
    m = re.search(re.escape(name) + r"[^=]*=\s*\{", src)
    if not m:
        raise ValueError("could not locate object: " + name)
    start = src.index("{", m.end() - 1)
    end = _match_brace(src, start)
    return src[start + 1:end - 1]


# ── Load the three source modules ────────────────────────────────────────────
def load():
    strings_src = _strip_comments(_read(os.path.join(_LOCALES, "strings.ts")))
    i18n_src = _read(os.path.join(_LOCALES, "i18n.ts"))
    registry_src = _read(os.path.join(_LOCALES, "registry.ts"))

    # NAMESPACES = [ '...', ... ]
    ns_block = re.search(r"NAMESPACES\s*=\s*\[(.*?)\]", i18n_src, re.S).group(1)
    namespaces = re.findall(r"'([^']+)'", ns_block)

    # registered language codes + status tier from the LANGUAGES array
    reg_codes = re.findall(r"code:\s*'([^']+)'", registry_src)
    reg_status = dict(
        re.findall(r"code:\s*'([^']+)'[\s\S]*?status:\s*'([^']+)'", registry_src)
    )

    table_body = _extract_named_object(strings_src, "STRINGS")
    table = {}
    for ns, ns_body in _parse_object(table_body):
        entries = {}
        for key, langmap_src in _parse_object(ns_body[1:-1]):
            pairs = _parse_object(langmap_src[1:-1])
            entries[key] = {code: _unquote(v) for code, v in pairs}
        table[ns] = entries
    return namespaces, reg_codes, table, reg_status


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def placeholders(s):
    return set(_PLACEHOLDER_RE.findall(s))


# ── Checks ───────────────────────────────────────────────────────────────────
def main():
    namespaces, reg_codes, table, reg_status = load()
    reg_set = set(reg_codes)

    # 1. Namespace parity between i18n.ts and STRINGS.
    for ns in namespaces:
        check(ns in table, f"namespace '{ns}' declared in i18n.ts but missing in STRINGS")
    for ns in table:
        check(ns in namespaces, f"namespace '{ns}' in STRINGS not declared in i18n.ts")

    # 2/3/4/5/7. Per-key checks.
    total_keys = 0
    for ns, entries in table.items():
        check(len(entries) > 0, f"namespace '{ns}' is empty")
        for key, lm in entries.items():
            total_keys += 1
            path = f"{ns}.{key}"
            for code in lm:  # 7. only registered languages appear
                check(code in reg_set, f"{path}: unregistered language code '{code}'")
            # 4. English must exist (deterministic final fallback anchor)
            check("en" in lm and lm["en"].strip() != "", f"{path}: missing/empty 'en'")
            # 3. first-class languages must cover every key
            for fc in FIRST_CLASS:
                check(fc in lm and lm[fc].strip() != "",
                      f"{path}: first-class language '{fc}' missing/empty")
            # 2. no empty values anywhere
            for code, val in lm.items():
                check(val.strip() != "", f"{path}: empty value for '{code}'")
            # 5. placeholder parity against English
            if "en" in lm:
                base = placeholders(lm["en"])
                for code, val in lm.items():
                    check(placeholders(val) == base,
                          f"{path}: placeholder mismatch in '{code}' "
                          f"(want {sorted(base)}, got {sorted(placeholders(val))})")

    # 6. critical safety strings present + carry verified numbers verbatim.
    mh = table.get("mental_health", {})
    for req in ("crisisTitle", "crisisBody", "callTeleManas", "callEmergency"):
        check(req in mh, f"mental_health.{req} missing (critical safety string)")
    crisis_blob = " ".join(
        v for k in ("callTeleManas", "callEmergency", "crisisBody") if k in mh
        for v in mh[k].values()
    )
    for num in VERIFIED_NUMBERS:
        check(num in crisis_blob,
              f"verified emergency number '{num}' not found in crisis strings")

    # ── Coverage report (honest per-language %) ──────────────────────────────
    print("HAVEN localization validation")
    print("=" * 60)
    print(f"namespaces: {len(table)}   keys: {total_keys}   languages: {len(reg_codes)}")
    print("-" * 60)
    print("coverage by language (authored keys / total):")
    for code in reg_codes:
        authored = sum(
            1 for entries in table.values() for lm in entries.values()
            if code in lm and lm[code].strip()
        )
        pct = (authored / total_keys * 100) if total_keys else 0
        tier = reg_status.get(code, "fallback")
        print(f"  {code:<9} {authored:>4}/{total_keys}  {pct:5.1f}%  ({tier})")
    print("-" * 60)

    if _FAILS:
        print(f"FAIL - {_PASSES} passed, {len(_FAILS)} failed:")
        for f in _FAILS:
            print("  x " + f)
        return 1
    print(f"PASS - all {_PASSES} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
