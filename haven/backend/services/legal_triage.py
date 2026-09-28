"""
legal_triage.py — Deterministic (NON-LLM) legal query understanding for HAVEN.

This module classifies a user's legal question WITHOUT any language model, so the
result is reproducible and cannot hallucinate. It produces:
  * a structured LegalQuery (category, subcategory, jurisdiction, state, urgency,
    immediate_danger, children_involved, language),
  * emergency detection + the right helplines (with source + verified_at metadata),
  * safe, GENERIC practical next-steps / clarifying questions / evidence checklists
    (these are practical scaffolding only — the authoritative LAW with citations
    comes from the verified corpus via legal_rag, never from this file),
  * an evidence-level (HIGH / MEDIUM / INSUFFICIENT_EVIDENCE) computed from the
    verified passages actually retrieved.

No legal sections, deadlines, fees or case citations are invented here. Helpline
numbers are stored as data with a source and a verified_at date, NOT presented as law.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TRIAGE_VERSION = "2026-09-25"
_VERIFIED_AT = "2026-09-25"

# ---------------- Helplines (metadata, NOT law) ----------------
HELPLINES: Dict[str, Dict[str, Any]] = {
    "emergency_112": {"name": "National Emergency Number", "number": "112",
                      "purpose": "Immediate police / fire / medical emergency",
                      "source": "Ministry of Home Affairs (ERSS)", "verified_at": _VERIFIED_AT},
    "women_181": {"name": "Women Helpline", "number": "181",
                  "purpose": "Women in distress — 24x7 support and referral",
                  "source": "Ministry of Women & Child Development", "verified_at": _VERIFIED_AT},
    "ncw_7827170170": {"name": "NCW Women Helpline", "number": "7827170170",
                       "purpose": "National Commission for Women 24x7 women's helpline",
                       "source": "National Commission for Women", "verified_at": _VERIFIED_AT},
    "childline_1098": {"name": "Childline", "number": "1098",
                       "purpose": "Children in need of care and protection",
                       "source": "Ministry of Women & Child Development", "verified_at": _VERIFIED_AT},
    "nalsa_15100": {"name": "NALSA Legal Aid Helpline", "number": "15100",
                    "purpose": "Free legal aid and advice",
                    "source": "National Legal Services Authority", "verified_at": _VERIFIED_AT},
    "telelaw_14454": {"name": "Tele-Law", "number": "14454",
                      "purpose": "Free pre-litigation legal advice",
                      "source": "Department of Justice", "verified_at": _VERIFIED_AT},
    "cyber_1930": {"name": "Cyber Crime Helpline", "number": "1930",
                   "purpose": "Report financial cyber fraud (report as early as possible)",
                   "source": "Indian Cyber Crime Coordination Centre (I4C), MHA", "verified_at": _VERIFIED_AT},
}
# Which helplines to surface per category (order = display priority).
_CATEGORY_HELPLINES: Dict[str, List[str]] = {
    "women_rights": ["ncw_7827170170", "women_181", "nalsa_15100"],
    "family": ["nalsa_15100", "telelaw_14454", "women_181"],
    "child_safety": ["childline_1098", "emergency_112", "ncw_7827170170"],
    "police": ["emergency_112", "women_181", "nalsa_15100"],
    "cyber": ["cyber_1930", "ncw_7827170170", "nalsa_15100"],
    "workplace": ["ncw_7827170170", "nalsa_15100", "women_181"],
    "legal_aid": ["nalsa_15100", "telelaw_14454"],
    "court_navigation": ["nalsa_15100", "telelaw_14454"],
    "general": ["nalsa_15100", "women_181", "telelaw_14454"],
}

# Indian States and Union Territories (lowercase) for jurisdiction extraction.
_INDIAN_STATES: List[str] = [
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa",
    "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala",
    "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland",
    "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura",
    "uttar pradesh", "uttarakhand", "west bengal", "andaman and nicobar", "chandigarh",
    "dadra and nagar haveli", "daman and diu", "delhi", "jammu and kashmir", "ladakh",
    "lakshadweep", "puducherry", "pondicherry",
]

# Category keyword sets. Each match scores 1; highest score wins (ties broken by
# _CATEGORY_PRIORITY). Phrases are matched as substrings on the lowercased question.
_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "women_rights": [
        "domestic violence", "dowry", "dahej", "cruelty", "498a", "beating me", "beats me",
        "beat me", "hit me", "hitting me", "abusive", "abuse me", "abused", "in-law", "in law",
        "sasural", "marital", "protection order", "restraining order", "streedhan", "wife beating",
        "harassing me at home", "violence at home", "maintenance from husband",
        "husband is threatening", "husband threatening", "husband threatens",
        "threatening me at home", "my husband beats", "my husband hits",
        "rights as a woman", "women rights", "women's rights", "woman's rights",
        "legal rights as a woman", "rights of a woman", "as a woman under",
        "घरेलू हिंसा", "दहेज", "दहेज उत्पीड़न", "क्रूरता", "मारता", "पीटता", "मारपीट",
        "पति मारता", "पति पीटता", "पति धमकी", "ससुराल", "घर में हिंसा", "महिला अधिकार",
        "महिला के अधिकार", "औरत के अधिकार",
    ],
    "family": [
        "divorce", "custody", "separation", "alimony", "guardian", "visitation", "mutual consent",
        "talaq", "khula", "marriage registration", "judicial separation", "child support",
        "adoption", "shaadi", "tofeeq", "annulment", "matrimonial",
        "तलाक", "विवाह", "शादी", "कस्टडी", "अभिरक्षा", "गुजारा भत्ता", "भरण पोषण",
        "आपसी सहमति", "विवाह विच्छेद", "न्यायिक पृथक्करण", "परिवार न्यायालय", "मुलाकात",
    ],
    "child_safety": [
        "pocso", "child abuse", "minor", "molest", "missing child", "childline", "child marriage",
        "kidnap", "sexual abuse of child", "my child was", "bacche", "baccha", "child labour",
        "बाल शोषण", "बाल यौन शोषण", "बच्चा गायब", "बच्चा गुम", "बच्चा लापता",
        "बच्चा खतरे में", "बाल विवाह",
    ],
    "police": [
        "fir", "police", "zero fir", "police refuse", "police station", "arrest", "complaint against",
        "lodge complaint", "register complaint", "thana", "police not", "diary entry",
        "पुलिस", "एफआईआर", "प्राथमिकी", "शिकायत दर्ज", "जीरो एफआईआर", "पुलिस मना",
        "पुलिस नहीं लिख", "थाना",
    ],
    "cyber": [
        "cyber", "online", "morphed", "leaked", "leak my", "blackmail", "sextortion", "social media",
        "facebook", "instagram", "whatsapp", "obscene", "hacked", "otp", "upi", "phishing",
        "fake profile", "revenge porn", "objectionable", "photo online", "video online", "1930",
        "ऑनलाइन", "साइबर", "धमकी", "ब्लैकमेल", "फोटो लीक", "अश्लील", "सोशल मीडिया",
        "ऑनलाइन धमकी", "यूपीआई धोखाधड़ी",
    ],
    "workplace": [
        "workplace", "office", "colleague", "my boss", "posh", "internal committee", "employer",
        "at work", "co-worker", "coworker", "manager", "senior at office", "icc", "local committee",
        "कार्यस्थल", "दफ्तर", "यौन उत्पीड़न", "सहकर्मी", "आंतरिक समिति", "कार्यस्थल शिकायत",
    ],
    "legal_aid": [
        "free lawyer", "legal aid", "cannot afford", "can't afford", "free legal", "afford a lawyer",
        "nalsa", "tele-law", "telelaw", "no money for lawyer", "muft vakil", "free legal help",
        "government lawyer", "free government lawyer", "free advocate", "government advocate",
        "court appointed", "court-appointed", "appoint a lawyer", "provide a lawyer",
        "lawyer for free", "sarkari vakil", "state legal services", "dlsa", "slsa", "lok adalat",
        "कानूनी सहायता", "कानूनी मदद", "मुफ्त वकील", "निःशुल्क कानूनी", "वकील", "कानूनी सलाह",
        "सरकारी वकील",
    ],
    "court_navigation": [
        "case status", "cnr", "ecourts", "e-court", "hearing date", "next date", "next hearing",
        "file case online", "court fee", "e-filing", "efiling", "check my case", "case number",
        "केस स्टेटस", "सुनवाई की तारीख", "मुकदमे की स्थिति", "ई-फाइलिंग",
    ],
}
_CATEGORY_PRIORITY = ["child_safety", "women_rights", "cyber", "workplace", "police",
                      "family", "court_navigation", "legal_aid", "general"]

# Immediate-danger signals → urgency = "emergency", immediate_danger = True.
_IMMEDIATE_DANGER = [
    "right now", "hitting me", "beating me", "attacking", "kill me", "kill her", "kill us",
    "going to kill", "threatening to kill", "he will kill", "bleeding", "has a knife", "weapon",
    "trying to kill", "save me", "help me now", "locked me", "not safe right now", "in danger now",
    "about to", "maar raha", "jaan se maar", "khatra", "bacha lo", "abhi maar", "gun",
    "जान से मार", "मार डालेगा", "बचाओ", "चाकू", "बंदूक", "अभी मार", "मार रहा है",
]
# Time-sensitive but not immediately life-threatening → urgency = "high".
_HIGH_URGENCY = [
    "stalking", "following me", "threat", "threatening", "missing child", "kidnap", "sextortion",
    "blackmail", "cyber fraud", "money stolen", "fraud", "leaked", "morphed", "abusive", "harass",
    "thrown out", "kicked out", "forced", "acid",
    "धमकी", "धमका", "पीछा", "पीछा कर", "मारता", "पीटता",
]
_CHILD_SIGNALS = ["child", "children", "son", "daughter", "kids", "kid", "minor", "custody",
                  "baccha", "bacche", "bachche", "beta", "beti", "infant", "toddler",
                  "बच्चा", "बच्चे", "बेटा", "बेटी", "कस्टडी"]

# Hinglish (romanised Hindi) signal tokens for language detection.
_HINGLISH_TOKENS = {
    "mujhe", "mera", "meri", "mere", "pati", "patni", "kya", "kaise", "chahiye", "nahi", "nahin",
    "hai", "karna", "karo", "shaadi", "talaq", "sasural", "bacha", "baccha", "bacche", "dahej",
    "maar", "raha", "rahe", "kaun", "kahan", "kaisa", "hoga", "karu", "karun", "vakil",
}

@dataclass
class LegalQuery:
    """Structured, deterministic understanding of a legal question."""
    raw_question: str
    category: str = "general"
    subcategory: str = ""
    jurisdiction: str = "India"
    state: str = ""
    language: str = "en"            # "en" | "hi" | "hinglish"
    urgency: str = "normal"         # "normal" | "high" | "emergency"
    immediate_danger: bool = False
    children_involved: bool = False
    tokens: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category, "subcategory": self.subcategory,
            "jurisdiction": self.jurisdiction, "state": self.state, "language": self.language,
            "urgency": self.urgency, "immediate_danger": self.immediate_danger,
            "children_involved": self.children_involved,
        }


def _tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1]


def detect_language(question: str, hint: Optional[str] = None) -> str:
    if hint in ("en", "hi", "hinglish"):
        return hint
    if re.search(r"[ऀ-ॿ]", question):   # Devanagari
        return "hi"
    toks = set(_tokenize(question))
    if toks & _HINGLISH_TOKENS:
        return "hinglish"
    return "en"


def extract_state(question: str, hint: Optional[str] = None) -> str:
    if hint:
        h = hint.strip().lower()
        for st in _INDIAN_STATES:
            if st == h or st in h:
                return st.title()
    q = question.lower()
    for st in _INDIAN_STATES:
        if re.search(r"\b" + re.escape(st) + r"\b", q):
            return "Puducherry" if st == "pondicherry" else st.title()
    return ""

def classify_category(question: str) -> str:
    # Normalize first so surface-form variants (e.g. the Devanagari nukta in
    # "तलाक़") fold onto the literal keyword ("तलाक") the map already carries.
    q = normalize_devanagari(question.lower())
    scores: Dict[str, int] = {}
    for cat, kws in _CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in kws if kw in q)
    best = max(scores.values()) if scores else 0
    if best == 0:
        # Literal keywords found nothing. Fall back to the deterministic concept
        # map, which resolves transliteration / colloquial variants the literal
        # list cannot enumerate (e.g. "talaak"/"talak"/"talaaq" → divorce → family).
        # This can only RAISE a query out of "general"; it never overrides a
        # category the literal keywords already picked, so existing routing is
        # preserved exactly.
        concepts = match_concepts(question)
        category = concepts[0]["category"] if concepts else "general"
    else:
        # Tie-break by priority order.
        category = "general"
        for cat in _CATEGORY_PRIORITY:
            if scores.get(cat, 0) == best:
                category = cat
                break
    # Child-danger override (single source of truth, shared with build_query): a
    # child who is missing / abused / in danger is a CHILD-SAFETY matter even when
    # the base keywords route elsewhere or nowhere — UNLESS the question is clearly
    # a custody / divorce / maintenance (family-law) matter. child_safety is the
    # highest-priority category, so this can only raise priority, never lower it.
    ql = question.lower()
    if (_children_involved(question)
            and any(w in ql for w in ("missing", "kidnap", "molest", "pocso", "abused",
                                      "abuse", "abusing", "trafficking", "in danger", "hurt",
                                      "touching", "beating", "beaten", "raped", "rape"))
            and not any(w in ql for w in ("custody", "divorce", "visitation", "maintenance"))):
        category = "child_safety"
    return category


def detect_urgency(question: str) -> tuple[str, bool]:
    q = question.lower()
    if any(sig in q for sig in _IMMEDIATE_DANGER):
        return "emergency", True
    if any(sig in q for sig in _HIGH_URGENCY):
        return "high", False
    return "normal", False


def _children_involved(question: str) -> bool:
    q = question.lower()
    return any(re.search(r"\b" + re.escape(s) + r"\b", q) for s in _CHILD_SIGNALS)


def build_query(question: str, language_hint: Optional[str] = None,
                state_hint: Optional[str] = None) -> LegalQuery:
    """Deterministically classify a raw question into a LegalQuery."""
    question = (question or "").strip()
    category = classify_category(question)
    # (Child-danger routing now lives inside classify_category so both entry points
    # agree; build_query only adds urgency semantics on top.)
    urgency, immediate = detect_urgency(question)
    # A child-safety topic or missing/abused child is always at least high urgency.
    if category == "child_safety" and urgency == "normal":
        urgency = "high"
    return LegalQuery(
        raw_question=question,
        category=category,
        jurisdiction="India",
        state=extract_state(question, state_hint),
        language=detect_language(question, language_hint),
        urgency=urgency,
        immediate_danger=immediate,
        children_involved=_children_involved(question),
        tokens=_tokenize(question),
    )

# ---------------- Practical scaffolding (GENERIC, non-fabricated) ----------------
# These are safe, general practical prompts/steps. They deliberately contain NO
# specific section numbers, deadlines, fees or case names — those come only from the
# verified corpus. Framed as practical guidance, not as statements of law.
_CLARIFYING_QUESTIONS: Dict[str, List[str]] = {
    "women_rights": [
        "Are you currently safe, or is the person who is harming you nearby right now?",
        "Which state or city are you in? (this decides which court and police station apply)",
        "Do you want protection/safety, a criminal complaint, or financial maintenance — or more than one?",
    ],
    "family": [
        "Is this about divorce, custody, maintenance, or something else?",
        "Which state or city are you in, and where was the marriage?",
        "Are both parties willing (mutual), or is this contested?",
    ],
    "child_safety": [
        "Is the child safe right now? If a child is in immediate danger, call 112 or Childline 1098.",
        "How old is the child, and what is your relationship to them?",
        "Which state or city are you in?",
    ],
    "police": [
        "Has any incident already happened, or are you trying to prevent one?",
        "Which state, city and police station area does this relate to?",
        "Has the police already refused to help, or have you not approached them yet?",
    ],
    "cyber": [
        "What exactly happened — was content leaked/morphed, an account hacked, or money taken?",
        "Do you still have the links, messages, screenshots or transaction details?",
        "Which state or city are you in?",
    ],
    "workplace": [
        "Did the incident happen at your workplace or in a work context?",
        "Does your organisation have an Internal Committee (IC) you know of?",
        "Are you a current employee, and which state/city is the workplace in?",
    ],
    "legal_aid": [
        "Do you want a free lawyer, free legal advice, or help filing a case?",
        "Which state, and district or city, are you in?",
    ],
    "court_navigation": [
        "Do you already have a case number or CNR number?",
        "Is it a District Court, High Court, or another forum?",
    ],
    "general": [
        "Could you tell me a bit more about the situation you need legal help with?",
        "Which state or city are you in?",
    ],
}

_NEXT_STEPS: Dict[str, List[str]] = {
    "women_rights": [
        "If you are in immediate danger, call 112 or the women's helpline 181 first.",
        "Write down what happened with dates, and keep any medical records, messages or photos.",
        "You can approach the police, a Protection Officer, or a free legal-aid lawyer — the verified sources below explain your options.",
    ],
    "family": [
        "Gather your marriage and identity documents and note key dates.",
        "Free legal advice is available through NALSA (15100) or Tele-Law (14454) if you cannot afford a lawyer.",
        "The verified sources below explain the relevant grounds and process; a family lawyer can file for you.",
    ],
    "child_safety": [
        "If a child is in immediate danger, call 112 now, or Childline 1098.",
        "Note down what you observed and preserve any evidence safely.",
        "The verified sources below explain mandatory reporting and who to contact.",
    ],
    "police": [
        "You can report at any police station; note down officers' names and get a copy/acknowledgement.",
        "Keep any evidence and a written account of events.",
        "The verified sources below explain FIR/Zero-FIR and what to do if police refuse.",
    ],
    "cyber": [
        "Do NOT delete anything — save links, screenshots, usernames and transaction IDs.",
        "For money fraud, report as early as possible on the cyber helpline 1930 and cybercrime.gov.in.",
        "The verified sources below explain reporting and the relevant offences.",
    ],
    "workplace": [
        "Note dates, what was said/done, and any witnesses or messages.",
        "Complaints usually go to your organisation's Internal Committee — the verified sources explain this.",
        "Free legal advice is available via NALSA (15100) if you need it.",
    ],
    "legal_aid": [
        "Women and children are entitled to free legal aid regardless of income.",
        "Call NALSA 15100, or visit your District Legal Services Authority (DLSA) in the court complex.",
        "For free legal advice, Tele-Law (14454) can connect you to a panel lawyer.",
    ],
    "court_navigation": [
        "Case status can be checked on the official eCourts portal (ecourts.gov.in) using the CNR number.",
        "This tool does not fetch live case status — always verify on eCourts or with your advocate.",
    ],
    "general": [
        "Tell me more about your situation so I can point you to the right verified information.",
        "For free legal advice you can call NALSA 15100 or Tele-Law 14454.",
    ],
}

_EVIDENCE_CHECKLIST: Dict[str, List[str]] = {
    "women_rights": [
        "Medical records / MLC if there were injuries", "Photos of injuries or damage",
        "Threatening messages, call logs, emails", "Names and contacts of any witnesses",
        "Proof of marriage and of shared household", "List/receipts of streedhan or dowry items",
    ],
    "family": [
        "Marriage certificate / proof of marriage", "Identity and address proof",
        "Financial documents (income, assets) for maintenance/alimony",
        "Records relevant to the child's care (for custody)", "Any prior agreements or notices",
    ],
    "child_safety": [
        "Any messages, images or documents (kept safely)", "Details of when and where it happened",
        "The child's age and identity details", "Names of any witnesses or other affected children",
    ],
    "police": [
        "A written, dated account of what happened", "Any photos, messages or physical evidence",
        "Names/contacts of witnesses", "Copy or acknowledgement of any complaint filed",
    ],
    "cyber": [
        "Screenshots and the exact URLs/links", "Offending usernames / profile links",
        "Transaction IDs, UPI refs and bank statements (for fraud)",
        "Any emails/SMS with headers", "Do not delete the original messages",
    ],
    "workplace": [
        "Dates, times and description of each incident", "Emails, chats or messages",
        "Names of witnesses", "Your appointment letter / proof of employment",
        "Any complaint already made to the employer or IC",
    ],
    "legal_aid": [
        "Identity and address proof", "Income proof or category document (if any)",
        "Copies of documents about your legal problem",
    ],
    "court_navigation": [
        "Your CNR number or case number", "Names of the parties",
        "The court and district where the case is filed",
    ],
    "general": ["A written account of the situation", "Any relevant documents or messages"],
}

def helplines_for(category: str, immediate_danger: bool = False) -> List[Dict[str, Any]]:
    """Return helpline dicts (with source + verified_at) relevant to a category."""
    keys = list(_CATEGORY_HELPLINES.get(category, _CATEGORY_HELPLINES["general"]))
    if immediate_danger and "emergency_112" not in keys:
        keys.insert(0, "emergency_112")
    seen, out = set(), []
    for k in keys:
        if k in HELPLINES and k not in seen:
            seen.add(k)
            out.append(dict(HELPLINES[k]))
    return out

def compute_evidence_level(passages: List[Dict[str, Any]]) -> str:
    """Deterministic evidence confidence from the VERIFIED passages retrieved.

    Everything in the corpus is verified, so any hit is at least MEDIUM; HIGH needs
    either two primary (tier1) sources or one strong-scoring primary source.
    """
    if not passages:
        return "INSUFFICIENT_EVIDENCE"
    n_tier1 = sum(1 for p in passages if str(p.get("authority_level", "")).startswith("tier1"))
    best = 0.0
    for p in passages:
        s = p.get("score") or p.get("relevance_score")
        if isinstance(s, (int, float)):
            best = max(best, float(s))
    if n_tier1 >= 2 or (n_tier1 >= 1 and best >= 0.70):
        return "HIGH"
    return "MEDIUM"


def triage(question: str, language_hint: Optional[str] = None,
           state_hint: Optional[str] = None) -> Dict[str, Any]:
    """Full deterministic triage of a legal question (no LLM, no fabrication)."""
    q = build_query(question, language_hint, state_hint)
    cat = q.category
    return {
        **q.to_dict(),
        "emergency": q.urgency == "emergency",
        "clarifying_questions": list(_CLARIFYING_QUESTIONS.get(cat, _CLARIFYING_QUESTIONS["general"])),
        "next_steps": list(_NEXT_STEPS.get(cat, _NEXT_STEPS["general"])),
        "evidence_checklist": list(_EVIDENCE_CHECKLIST.get(cat, _EVIDENCE_CHECKLIST["general"])),
        "helplines": helplines_for(cat, q.immediate_danger),
        "legal_aid": legal_aid_block(),
        "triage_version": TRIAGE_VERSION,
    }


def legal_aid_block() -> Dict[str, Any]:
    """Free legal-aid escalation info (helplines are data, not law)."""
    return {
        "note": ("Women and children are entitled to free legal aid regardless of income. "
                 "You can get a free lawyer or free legal advice through the Legal Services Authorities."),
        "helplines": [dict(HELPLINES["nalsa_15100"]), dict(HELPLINES["telelaw_14454"])],
    }


# ---------------- Hybrid-retrieval scoring helpers (pure, testable) ----------------
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for", "is", "am",
    "are", "was", "were", "be", "been", "do", "does", "did", "how", "what", "when", "where",
    "why", "who", "which", "can", "could", "should", "would", "my", "me", "i", "you", "your",
    "he", "she", "it", "they", "them", "his", "her", "we", "our", "us", "this", "that", "these",
    "those", "with", "from", "at", "by", "as", "about", "into", "want", "need", "get", "there",
    "have", "has", "will", "shall", "may", "any", "some", "please", "help", "tell", "know",
}
_AUTHORITY_WEIGHT = {
    "tier1_primary_statute": 1.0, "tier1_primary_authority": 0.95,
    "tier2_official_explanatory": 0.80, "tier3_secondary": 0.60,
}
_DEFAULT_AUTHORITY_WEIGHT = 0.70

# Minimal Hindi (Devanagari) function-word stopword set. Deliberately EXCLUDES
# मुझे / चाहिए (the spec wants those preserved as tokens) and EXCLUDES every
# substantive legal term (कानूनी, तलाक, कस्टडी, पुलिस, दहेज, धमकी, बच्चे ...).
# These are pure grammatical particles / generic verbs / interrogatives that never
# carry legal meaning on their own. Keeping them out of the token stream stops a
# multi-word keyword phrase (e.g. "पुलिस एफआईआर नहीं लिख रही") from leaking a generic
# token ("नहीं", "मिल", "रही") that would otherwise cross-match unrelated queries.
_HINDI_STOPWORDS = {
    "में", "से", "को", "का", "की", "के", "है", "हैं", "हूँ", "हूं", "और", "या",
    "पर", "कि", "यह", "वह", "भी", "तो", "ने", "हो", "था", "थी", "थे", "रहा",
    "रही", "रहे", "गया", "गई", "गए", "पास", "लिए", "साथ", "तक", "एक", "मेरा",
    "मेरी", "मेरे", "नहीं", "मिल", "मिला", "मिलेगा", "कर", "करना", "करें", "करो",
    "दे", "दो", "दिया", "ले", "लो", "लिया", "लें", "किया", "वाले", "वाला", "वाली",
    "कोई", "क्या", "कैसे", "कहाँ", "कहां", "कौन", "जो", "बात", "किसी", "किसे",
    "दोनों", "अपने", "अपनी", "उस", "इस", "हम", "आप", "तुम", "जब", "अब",
}

# Unicode-aware token pattern: ASCII alphanumerics (keeps "498a", "13b", "66c")
# OR a run of Devanagari letters/matras/digits (U+0900–U+0963, U+0966–U+097F).
# The two danda punctuation marks (U+0964 ।, U+0965 ॥) are excluded so a trailing
# danda never fuses onto a real word. Devanagari has no case, so .lower() is a
# no-op for it and English lowercasing behaviour is unchanged.
_WORD_RE = re.compile(r"[a-z0-9]+|[ऀ-ॣ०-ॿ]+")


def _raw_tokens(text: str) -> List[str]:
    """All Unicode-aware tokens (Latin+digit and Devanagari) from lowercased text."""
    return _WORD_RE.findall((text or "").lower())


def query_tokens(question: str) -> List[str]:
    """Meaningful tokens for keyword retrieval, Unicode-aware (English + Hindi + Hinglish).

    English tokens keep the original rule (len>2, drop English stopwords). Devanagari
    tokens are kept when len>2 and not a Hindi function-word stopword. This restores
    keyword retrieval for Devanagari queries such as "मुझे तलाक चाहिए" (→ मुझे, तलाक,
    चाहिए) while leaving ASCII/Hinglish tokenization byte-for-byte identical.
    """
    out, seen = [], set()
    for t in _raw_tokens(question):
        if len(t) <= 2 or t in seen:
            continue
        if t in _STOPWORDS or t in _HINDI_STOPWORDS:
            continue
        seen.add(t)
        out.append(t)
    return out


def field_token_set(text: str) -> set:
    """Whole-word token set of a corpus field, for precise (non-substring) matching.

    Applies the same stopword filter as query_tokens so a curated keyword phrase can
    never contribute a generic particle/verb token (e.g. "नहीं", "मिल", "कर") as a
    matchable term. Substantive legal terms are untouched, so real matches survive.
    """
    return {t for t in _raw_tokens(text)
            if len(t) >= 2 and t not in _STOPWORDS and t not in _HINDI_STOPWORDS}


# ============================================================================
# Deterministic normalization + legal-topic query expansion.
#
# Problem: colloquial / transliterated queries such as "talaak", "talak",
# "talaaq" or "तलाक़" (with a nukta) must route to the SAME legal topic and
# retrieve the SAME verified sources as the canonical "divorce"/"talaq"/"तलाक",
# WITHOUT lowering any grounding threshold and WITHOUT an ever-growing raw
# keyword list. This layer is three small, reusable, framework-free parts:
#
#   1. normalize_devanagari() — Unicode NFC + nukta fold, so surface variants
#      like "तलाक़"/"क़" collapse onto their nukta-less base ("तलाक"/"क").
#   2. phonetic_fold()        — a stable romanisation key for Latin tokens
#      (ph→f, w→v, q→k, x→ks, z→j, then collapse repeated letters), so the many
#      spellings of one word converge (talaq/talaak/talak/talaaq → "talak") and
#      need not be enumerated.
#   3. LEGAL_CONCEPTS         — a small, MAINTAINABLE map of legal concept →
#      (category, aliases across scripts, corpus-present expansion terms).
#
# Aliases are matched by whole-word / phonetic key (never a bare substring for
# single words), and a concept only ever contributes its OWN on-topic canonical
# terms, so expansion can never pull an unrelated topic's source into a result
# and an unrelated query is never expanded (no-context guarantees preserved).
# Nothing here logs the raw query.
# ============================================================================

_NUKTA = "़"      # Devanagari sign nukta (combining) — folded for matching.
_LATIN_RE = re.compile(r"^[a-z]+$")


def normalize_devanagari(text: str) -> str:
    """Unicode-normalize text and fold the Devanagari nukta so precomposed and
    decomposed nukta forms match a nukta-less corpus term.

    e.g. "तलाक़" (…क + ़) and the precomposed "क़" (U+0958) both fold to
    "तलाक"/"क". ASCII text is unchanged. Case is left to the caller.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text).replace(_NUKTA, "")
    return unicodedata.normalize("NFC", decomposed)


def phonetic_fold(token: str) -> str:
    """Stable romanisation key for a single Latin token (else returned unchanged).

    Folds the arbitrary transliteration choices Hindi speakers make (ph/f, w/v,
    q/k, x/ks, z/j) and collapses repeated letters, so talaq / talaak / talak /
    talaaq all converge to "talak". Non-Latin (Devanagari) tokens are returned
    unchanged so they compare by their normalized form instead.
    """
    t = (token or "").lower()
    if not _LATIN_RE.match(t):
        return t
    t = t.replace("ph", "f")
    t = t.replace("w", "v").replace("q", "k").replace("x", "ks").replace("z", "j")
    t = re.sub(r"(.)\1+", r"\1", t)   # collapse any run of a repeated letter
    return t


def match_profile(query_toks: List[str], structured_text: str, body_text: str,
                  doc_category: str, query_category: str):
    """Precise whole-word overlap of query tokens against a passage.

    Returns (structured_hits, body_hits, category_match). "structured" = title,
    section, act name and the curated keyword list (high-signal); "body" = the
    passage text. Whole-word membership (not substring) is used, so "pati" no
    longer matches "participating" and "कानून" no longer matches "कानूनी".
    """
    s = field_token_set(structured_text)
    b = field_token_set(body_text)
    sh = sum(1 for t in query_toks if t in s)
    bh = sum(1 for t in query_toks if t in b)
    cm = bool(query_category and doc_category and doc_category == query_category)
    return sh, bh, cm


def precise_relevance(query_toks: List[str], structured_hits: int, body_hits: int,
                      category_match: bool) -> float:
    """Field-weighted keyword relevance in [0,1] used as the `keyword` term in ranking.

    Curated-field (title/section/act/keywords) hits count full weight; body hits are
    discounted; a category match adds a small bonus so the primary legal source for a
    topic outranks incidental navigation/document hits.
    """
    n = max(1, len(query_toks))
    base = (1.0 * structured_hits + 0.4 * body_hits) / n
    if category_match:
        base += 0.15
    return max(0.0, min(1.0, base))


def keyword_match_ratio(searchable_text: str, tokens: List[str]) -> float:
    """Fraction of query tokens present in a passage's searchable text (0..1)."""
    if not tokens:
        return 0.0
    low = (searchable_text or "").lower()
    hit = sum(1 for t in tokens if t in low)
    return hit / len(tokens)


def authority_weight(level: str) -> float:
    return _AUTHORITY_WEIGHT.get(str(level or ""), _DEFAULT_AUTHORITY_WEIGHT)


def blended_score(semantic: float, keyword: float, authority: float,
                  semantic_available: bool) -> float:
    """Blend semantic similarity, keyword overlap and source authority into one score."""
    if semantic_available:
        return 0.55 * semantic + 0.30 * keyword + 0.15 * authority
    return 0.75 * keyword + 0.25 * authority


# ---------------- Retrieval-quality FLOOR + citation validation (audit #12) ----------------
# Deterministic gate that decides whether the passages that survived
# legal_rag._merge_rerank are relevant ENOUGH to ground a generated answer.
# "Some source was retrieved" must NOT automatically mean grounded=True: a passage
# kept only on a single incidental keyword hit is not sufficient evidence. This
# reuses the signals legal_rag already attaches to every ranked passage
# (_blended, _kw_ratio, _precise_hits, _cat_match) plus the raw semantic `score`
# — no new/parallel scoring model is introduced. Thresholds are env-overridable.
GROUNDING_MIN_BLENDED = float(os.getenv("HAVEN_LEGAL_GROUNDING_MIN_BLENDED", "0.40"))
GROUNDING_MIN_KW_RATIO = float(os.getenv("HAVEN_LEGAL_GROUNDING_MIN_KW_RATIO", "0.50"))
# Authoritative semantic-retrieval floor. This MIRRORS legal_rag.MIN_SCORE (0.55):
# retrieve() already discards any $vectorSearch hit whose similarity score is below
# it, so a passage that still carries a semantic `score` has, by the pipeline's own
# definition, cleared the relevance bar. Used as the semantic-qualification signal
# when a passage has NOT been through _merge_rerank (i.e. carries no derived
# `_blended`) — e.g. a canonical/normalized source handed straight to answer().
GROUNDING_MIN_SEMANTIC = float(os.getenv("HAVEN_LEGAL_GROUNDING_MIN_SEMANTIC", "0.55"))


def normalize_passage(passage: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical relevance VIEW of a retrieved passage, independent of which
    retrieval/rerank implementation produced it.

    The reranker (legal_rag._merge_rerank) attaches derived fields
    (_blended/_kw_ratio/_precise_hits/_cat_match) to every passage it ranks, but
    those are private to that implementation. A passage may also arrive WITHOUT
    them (e.g. injected directly, or a future retrieval backend that only produces
    a raw semantic score). The grounding gate must not silently mis-classify such a
    passage as weak. This step produces the stable contract the floor operates on:

        semantic_score : raw $vectorSearch similarity (None if keyword-only)
        blended        : reranker's field-weighted score (None if not reranked)
        kw_ratio       : precise-keyword coverage ratio (0.0 if absent)
        precise_hits   : count of precise whole-word hits (0 if absent)
        cat_match      : on-topic category match (False if absent)
    """
    score = passage.get("score")
    semantic_score = float(score) if isinstance(score, (int, float)) else None
    blended = passage.get("_blended")
    return {
        "semantic_score": semantic_score,
        "blended": float(blended) if isinstance(blended, (int, float)) else None,
        "kw_ratio": float(passage.get("_kw_ratio") or 0.0),
        "precise_hits": int(passage.get("_precise_hits") or 0),
        "cat_match": bool(passage.get("_cat_match")),
    }


def passage_qualifies(passage: Dict[str, Any]) -> bool:
    """A single passage is strong enough to help ground an answer when it has REAL,
    non-incidental support (not merely a lone substring/keyword hit). Operates on
    the canonical `normalize_passage` contract, so it never depends on a private
    rerank field simply *existing*:

      * SEMANTIC support: a genuine similarity hit. When the reranker computed a
        blended score we require it to clear the blended floor (unchanged
        production behaviour); otherwise we fall back to the authoritative semantic
        retrieval floor (retrieve() already dropped anything below it), OR
      * it is on-topic (category match) with >=1 precise whole-word token hit, OR
      * it has >=2 precise whole-word hits (strong lexical overlap), OR
      * a majority of the query's tokens are precisely present (kw_ratio floor).
    """
    n = normalize_passage(passage)
    sem = n["semantic_score"]
    blended = n["blended"]
    if sem is not None:
        # Reranked passage -> keep the stricter blended floor; un-reranked passage
        # (no _blended) -> trust the semantic floor retrieve() already enforced.
        if blended is not None:
            if blended >= GROUNDING_MIN_BLENDED:
                return True
        elif sem >= GROUNDING_MIN_SEMANTIC:
            return True
    if n["cat_match"] and n["precise_hits"] >= 1:
        return True
    if n["precise_hits"] >= 2:
        return True
    if n["kw_ratio"] >= GROUNDING_MIN_KW_RATIO:
        return True
    return False


def assess_relevance(passages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic retrieval-quality floor for the grounding decision.

    Returns {passes, best_blended, qualifying, reason}. `passes` is True only when
    at least one retrieved passage clears passage_qualifies(); otherwise the caller
    MUST fall back to the safe no-context / insufficient-evidence path and NOT call
    the LLM merely because weak sources exist.
    """
    if not passages:
        return {"passes": False, "best_blended": 0.0, "qualifying": 0, "reason": "no_passages"}
    best = 0.0
    qualifying = 0
    for p in passages:
        best = max(best, float(p.get("_blended") or 0.0))
        if passage_qualifies(p):
            qualifying += 1
    passes = qualifying > 0
    return {"passes": passes, "best_blended": round(best, 6), "qualifying": qualifying,
            "reason": "ok" if passes else "below_relevance_floor"}


_CITATION_RE = re.compile(r"\[(\d{1,3})\]")


def validate_citations(answer_text: str, n_sources: int) -> Dict[str, Any]:
    """Validate the [n] citation markers in a generated legal answer against the
    number of sources ACTUALLY retrieved (deterministic, no LLM).

    A marker is INVALID (a fabricated citation id) when it is 0 or greater than
    n_sources — i.e. it references a source retrieval never returned. The ABSENCE
    of markers is allowed: the retrieved sources are still attached to the response
    and an ungrounded-looking marker is never invented on the model's behalf.

    Returns {valid, cited, invalid, reason}. On `valid=False` the caller must NOT
    mark grounded=True; it degrades safely, preserves the valid retrieved sources
    and never surfaces the hallucinated citation.
    """
    cited = sorted({int(m) for m in _CITATION_RE.findall(answer_text or "")})
    if n_sources <= 0:
        invalid = list(cited)               # no sources retrieved -> any marker is fabricated
    else:
        invalid = [c for c in cited if c < 1 or c > n_sources]
    return {"valid": not invalid, "cited": cited, "invalid": invalid,
            "reason": "ok" if not invalid else "fabricated_citation_id"}


# ---------------- Legal-topic concept map + query expansion ----------------
# A small, MAINTAINABLE intent map: canonical legal concept -> category, aliases
# in multiple scripts, and corpus-present expansion terms. This is NOT a giant
# keyword list — the normalization layer (nukta fold + phonetic key) generalizes
# each alias to its surface variants, so only canonical forms are listed here.
# To support a new colloquial term, add an alias/concept here (single source of
# truth), not scattered `if "..." in query` checks. Expansion terms are single,
# high-signal tokens that occur as whole words in the verified corpus, so they
# help BOTH the OR-regex prefilter and the precise whole-word reranker.
LEGAL_CONCEPTS: List[Dict[str, Any]] = [
    {"id": "divorce", "category": "family",
     "aliases": ["divorce", "talaq", "talak", "khula", "tofeeq", "annulment",
                 "तलाक", "विवाह विच्छेद", "विवाह-विच्छेद"],
     "expansions": ["divorce", "talaq", "तलाक"]},
    {"id": "maintenance", "category": "family",
     "aliases": ["maintenance", "alimony", "guzara", "kharcha",
                 "गुजारा भत्ता", "भरण पोषण", "भरण-पोषण"],
     "expansions": ["maintenance", "alimony"]},
    {"id": "custody", "category": "family",
     "aliases": ["custody", "guardianship", "visitation",
                 "कस्टडी", "अभिरक्षा", "संरक्षकता"],
     "expansions": ["custody"]},
    {"id": "domestic_violence", "category": "women_rights",
     "aliases": ["domestic violence", "dowry", "dahej", "cruelty",
                 "घरेलू हिंसा", "दहेज", "क्रूरता"],
     "expansions": ["dowry"]},
    {"id": "police_fir", "category": "police",
     "aliases": ["fir", "zero fir", "एफआईआर", "प्राथमिकी", "जीरो एफआईआर"],
     "expansions": ["fir"]},
    {"id": "cyber", "category": "cyber",
     "aliases": ["sextortion", "blackmail", "morphed", "revenge porn",
                 "साइबर", "ब्लैकमेल"],
     "expansions": ["cyber"]},
    {"id": "legal_aid", "category": "legal_aid",
     "aliases": ["legal aid", "free lawyer", "nalsa", "tele-law", "telelaw",
                 "कानूनी सहायता", "मुफ्त वकील"],
     "expansions": ["nalsa"]},
]


def _compile_concepts() -> List[Dict[str, Any]]:
    """Precompute, per concept, the match keys used at query time:
      * _norm_tokens — single-word aliases, nukta-normalized (whole-word match).
      * _folds       — phonetic keys of Latin single-word aliases len>=4 (fuzzy).
      * _phrases     — multi-word aliases, normalized (substring match).
    """
    compiled: List[Dict[str, Any]] = []
    for c in LEGAL_CONCEPTS:
        norm_tokens: set = set()
        folds: set = set()
        phrases: List[str] = []
        for alias in c["aliases"]:
            an = normalize_devanagari(str(alias).lower()).strip()
            if not an:
                continue
            parts = _raw_tokens(an)
            if len(parts) <= 1:
                norm_tokens.add(an)
                if _LATIN_RE.match(an) and len(an) >= 4:
                    folds.add(phonetic_fold(an))
            else:
                phrases.append(an)
        compiled.append({
            "id": c["id"], "category": c["category"],
            "expansions": list(c["expansions"]),
            "_norm_tokens": norm_tokens, "_folds": folds, "_phrases": phrases,
        })
    return compiled


_CONCEPTS_COMPILED = _compile_concepts()


def match_concepts(question: str) -> List[Dict[str, Any]]:
    """Deterministically detect which legal concept(s) a query is about.

    Matching is whole-word (normalized) or by phonetic key for Latin tokens
    (len>=4), plus substring for multi-word aliases — never a bare single-word
    substring, so an incidental fragment cannot trigger an unrelated concept.
    Returns matched concepts ordered by category priority (stable), so the first
    element is the highest-priority topic for a fallback classification.
    """
    qn = normalize_devanagari((question or "").lower())
    toks = set(_raw_tokens(qn))
    folds = {phonetic_fold(t) for t in toks if _LATIN_RE.match(t) and len(t) >= 4}
    hits: List[Dict[str, Any]] = []
    for c in _CONCEPTS_COMPILED:
        matched = bool(toks & c["_norm_tokens"]) or bool(folds & c["_folds"])
        if not matched:
            matched = any(ph in qn for ph in c["_phrases"])
        if matched:
            hits.append(c)
    hits.sort(key=lambda c: _CATEGORY_PRIORITY.index(c["category"])
              if c["category"] in _CATEGORY_PRIORITY else len(_CATEGORY_PRIORITY))
    return hits


def expand_query(question: str) -> List[str]:
    """On-topic expansion tokens for a query, from matched concepts (deduped).

    Empty when no concept is confidently detected — an unrelated query is never
    expanded, so no-context / no-hallucination behaviour is unchanged. Terms are
    normalized + tokenized so they compare identically to corpus field tokens.
    """
    out: List[str] = []
    seen: set = set()
    for c in match_concepts(question):
        for term in c["expansions"]:
            for t in _raw_tokens(normalize_devanagari(str(term).lower())):
                if t not in seen:
                    seen.add(t)
                    out.append(t)
    return out


def retrieval_tokens(question: str) -> List[str]:
    """query_tokens(question) + deterministic concept-expansion terms (deduped).

    This is the token list retrieval + precise reranking should use so that a
    colloquial / transliterated query (e.g. "talaak", "तलाक़") reaches the SAME
    verified sources as the canonical term WITHOUT lowering any grounding
    threshold. query_tokens() itself is intentionally left unchanged (its output
    is a stable public contract relied on elsewhere).
    """
    out: List[str] = []
    seen: set = set()
    for t in query_tokens(question):
        if t not in seen:
            seen.add(t)
            out.append(t)
    for t in expand_query(question):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

