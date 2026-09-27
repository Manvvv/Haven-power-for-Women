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

import re
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
        "घरेलू हिंसा", "दहेज", "दहेज उत्पीड़न", "क्रूरता", "मारता", "पीटता", "मारपीट",
        "पति मारता", "पति पीटता", "पति धमकी", "ससुराल", "घर में हिंसा",
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
        "कानूनी सहायता", "कानूनी मदद", "मुफ्त वकील", "निःशुल्क कानूनी", "वकील", "कानूनी सलाह",
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
    q = question.lower()
    scores: Dict[str, int] = {}
    for cat, kws in _CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in kws if kw in q)
    best = max(scores.values()) if scores else 0
    if best == 0:
        return "general"
    # Tie-break by priority order.
    for cat in _CATEGORY_PRIORITY:
        if scores.get(cat, 0) == best:
            return cat
    return "general"


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
    # Child-danger override: a child in danger/missing/abused is a child-safety matter,
    # not a family/custody matter — unless it is clearly a custody/divorce question.
    ql = question.lower()
    if (_children_involved(question)
            and any(w in ql for w in ("missing", "kidnap", "molest", "pocso", "abused",
                                      "abuse", "trafficking", "in danger", "hurt"))
            and not any(w in ql for w in ("custody", "divorce", "visitation", "maintenance"))):
        category = "child_safety"
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
