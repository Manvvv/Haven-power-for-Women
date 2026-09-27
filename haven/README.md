
# 🛡️ HAVEN — A Silent Shield, A Strong Voice

<div align="center">

![Haven Banner](https://img.shields.io/badge/HAVEN-AI%20for%20Social%20Good-be185d?style=for-the-badge&logo=shield&logoColor=white)
![Team](https://img.shields.io/badge/Team-Byte%20Me-f9a8d4?style=for-the-badge)

**An AI-powered safety platform that gives abused women a voice — even in silence.**

[Features](#-features) • [Tech Stack](#-tech-stack) • [Setup](#-setup) • [Architecture](#-architecture) • [API Docs](#-api-reference) • [Demo](#-demo)

</div>

---

## 📌 Problem Statement

Women in abusive relationships face a deadly paradox:

- **Constant surveillance** — abusers monitor every call, message, and app
- **No safe channel** — any direct cry for help risks discovery and escalation
- **No legal awareness** — only 14% of victims know their rights
- **Mental health crisis** — only 10% reach mental support services

> *"The biggest barrier to seeking help is not willingness — it is the abuser standing over her shoulder."*

**1 in 3 women** face violence globally. **30% of Indian women** have experienced domestic abuse. Haven is built for them.

---

## ✨ Features

### 🕵️ Discreet SOS — Steganography
Hide a distress message inside an innocent-looking image using **LSB steganography**. The image is posted on social media with `#HavenSOS` — it looks like a normal photo to the abuser, but Haven authorities can decode the hidden message.

```
Woman types keywords → AI expands message → FLUX.1 generates image
→ LSB encodes message in pixels → Download & post as normal photo
→ Authority Dashboard decodes → Response dispatched
```

### 🗣️ Voice-Activated Silent SOS
Configure a secret **"Safe Word"** or phrase. When spoken while HAVEN is active, the browser's speech recognition normalizes and hashes the phrase (SHA-256), captures exact high-accuracy GPS coordinates, and triggers an emergency alert to pre-configured trusted contacts — without playing loud sounds or revealing the trigger phrase.

```
User speaks safe word → SpeechRecognition API normalizes text
→ SHA-256 hash comparison → Geolocation API captures lat/lng
→ Voice SOS trigger API → Emergency WhatsApp alert & Authority case logged
```

### 🚨 Panic Button
Hold for **3 seconds** → GPS location captured → Emergency WhatsApp alert sent to trusted contact instantly.

### 🌸 AI Therapy — Aria
**Animated avatar** with real-time lip sync and facial expressions. 24/7 empathetic mental health support powered by Groq LLaMA 3.3.

- Mouth opens/closes during speech
- Eyebrows raise when listening
- Random blinking and idle head sway
- Web Speech API voice output

### ⚖️ Legal Assistant
Plain-language Indian law guidance powered by RAG (Retrieval Augmented Generation). Upload legal PDFs to expand the knowledge base.

Covers: PWDVA 2005 · Section 498A IPC · Dowry Act · Divorce Rights · Child Custody · Restraining Orders

### 🛡️ Authority Dashboard
For law enforcement and NGO partners:
- Decode SOS images and view hidden messages
- Monitor and manage live cases (MongoDB)
- Search culprit profiles using **AI vector similarity**
- Register and match perpetrator descriptions

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 14, TypeScript, Tailwind CSS |
| **Backend** | Python FastAPI, Uvicorn |
| **AI / LLM** | Groq (LLaMA 3.3 70B), Gemini 2.0 Flash |
| **Image Gen** | HuggingFace FLUX.1-schnell |
| **Database** | MongoDB Atlas + Vector Search |
| **Storage** | Cloudinary CDN |
| **Steganography** | Python Pillow (LSB encoding) |
| **Avatar** | Pure Canvas 2D API (no external deps) |
| **Voice** | Web Speech API |

---

## 📁 Project Structure

```
hacknaovate2.0/
├── haven/
│   ├── backend/
│   │   ├── main.py              # FastAPI app — all endpoints
│   │   ├── .env                 # API keys (never commit this)
│   │   ├── requirements.txt
│   │   └── setup_indexes.py     # MongoDB vector index setup
│   └── frontend/
│       ├── src/
│       │   ├── app/
│       │   │   ├── page.tsx           # Landing page
│       │   │   ├── dashboard/         # User dashboard + panic button
│       │   │   ├── sos/               # Discreet SOS flow
│       │   │   ├── therapy/           # Aria AI therapy chat
│       │   │   ├── legal/             # Legal assistant
│       │   │   └── authority/         # Officer dashboard
│       │   └── components/
│       │       ├── AriaCanvas.tsx     # Pure Canvas 2D avatar
│       │       └── PanicButton.tsx    # GPS panic button
│       ├── next.config.js
│       └── package.json
└── README.md
```

---

## ⚙️ Setup

> **Canonical project location.** This repository is the single source of truth for
> HAVEN. On the primary development machine it lives at
> `C:\Users\Sagar\OneDrive\Manav\hacknaovate2.0\haven` (the git repo root is the
> parent `hacknaovate2.0`). Always run the backend, frontend, tests, and scripts from
> this checkout. Do not create or run from a second copy elsewhere on disk — divergent
> copies caused a hard-to-trace runtime bug where the browser executed stale code.
> All paths below are relative to this checkout.

### Prerequisites

- Python 3.11+
- Node.js 18+
- MongoDB Atlas account (free M0 tier works)
- API keys (see below)

### 1. Clone and Navigate

```bash
git clone https://github.com/your-username/haven.git
cd haven
```

### 2. Backend Setup

```bash
cd haven/backend

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate
# Activate (Mac/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables

Create `haven/backend/.env`:

```env
# MongoDB Atlas (free at mongodb.com/atlas)
MONGO_ENDPOINT=mongodb+srv://user:password@cluster.mongodb.net/Haven

# Google Gemini (free at aistudio.google.com/apikey)
GEMINI_API_KEY=your_gemini_key

# Groq (free at console.groq.com)
GROQ_API_KEY=your_groq_key

# Cloudinary (free at cloudinary.com)
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# HuggingFace (free at huggingface.co/settings/tokens)
HF_API_KEY=your_hf_token
```

### 4. Start Backend

Run the backend as a direct local process (no Docker required):

```bash
cd haven/backend
uvicorn main:app --reload
# API:  http://127.0.0.1:8000
# Docs: http://127.0.0.1:8000/docs
```

> **Optional — local Redis** (for distributed rate limiting / durable cooldowns).
> HAVEN works out of the box **without** Redis (single-process in-memory fallback).
> To enable the shared backend, install and start a local Redis
> (`redis-server`, or Memurai / WSL on Windows), then set in `backend/.env`:
> `REDIS_URL=redis://localhost:6379/0` and `REDIS_ENABLED=true`.

### 5. Frontend Setup

```bash
cd haven/frontend

# Install dependencies
npm install

# Create frontend env
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
```

### 6. Start Frontend

```bash
npm run dev
# App runs at http://localhost:3000
```

**Production build & start** (run from `haven/frontend`):

```bash
npm run build   # compiles the Next.js production bundle (requires the platform SWC binary)
npm run start   # serves the built app on http://localhost:3000
```

> The dev webpack cache is relocated to the OS temp dir in `next.config.js` because
> OneDrive syncs and corrupts `.next/cache` mid-write, which blanks pages. Keep the
> checkout at the canonical path above and do not force the cache back under OneDrive.

### 7. Running the tests

```bash
# Backend (from haven/backend, with the venv active and requirements installed):
pytest

# Frontend safety/regression harnesses (from haven/frontend — no test runner needed):
node test/ariaVoice.spec.mjs
node test/dirForm.xss.security.mjs
node test/offlineQueue.security.mjs
```

---

## 🔌 API Reference

Base URL: `http://localhost:8000`

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/text-generation` | Expand keywords into distress message |
| `POST` | `/img-generation` | Generate innocent image via FLUX.1 |
| `POST` | `/encode` | Encode message in image (LSB) |
| `POST` | `/decode` | Decode hidden message from image |
| `POST` | `/therapy/chat` | AI therapy conversation (Groq) |
| `POST` | `/legal/query` | RAG legal question answering |
| `POST` | `/legal/upload-doc` | Upload legal PDF to knowledge base |
| `POST` | `/generate-poem` | Generate empowering poem |

### Voice SOS & Trusted Contacts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/voice-sos/config` | Save safe word (SHA-256 hashed) and settings |
| `GET` | `/voice-sos/config/{user_id}` | Get config status (never returns safe word) |
| `POST` | `/voice-sos/trigger` | Trigger real emergency SOS alert |
| `POST` | `/voice-sos/test` | Test mode trigger (simulates workflow, no alert sent) |
| `GET` | `/voice-sos/history/{user_id}` | Get event history for a user |
| `POST` | `/trusted-contacts` | Add/update trusted emergency contacts |
| `GET` | `/trusted-contacts/{user_id}` | List trusted emergency contacts |
| `GET` | `/voice-sos/analytics` | Get aggregated Voice SOS stats |

### Cases & Authority

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/cases` | Get all SOS cases (filter by severity/status) |
| `POST` | `/save-extracted-data` | Save decoded SOS to MongoDB |
| `PATCH` | `/cases/{case_id}` | Update case status |

### Culprit Database

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/culprit/report` | Register culprit profile with embedding (authenticated) |
| `POST` | `/culprit/find-match` | Search by name or AI vector similarity (**authority/admin only**) |

### AI Risk Classifier (decision support)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/ai/classify-risk` | Classify SOS text → severity, risk_score, indicators, confidence |
| `GET`  | `/ai/model-info` | Report active backend + whether it is DEMO mode |
| `GET`  | `/ai/embedding-info` | Embedding model + semantic-search status (DEMO/FALLBACK/ACTIVE) |
| `GET`  | `/ai/analysis/{case_id}` | Get stored AI analysis for a case (authority) |
| `PATCH`| `/ai/analysis/{case_id}/override` | Human review: accept/override AI, original prediction preserved (authority) |

### Search — Case & Profile Intelligence

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/search/cases` | Case search — `mode`: keyword/semantic/hybrid (authority) |
| `POST` | `/search/semantic` | Case search (dedicated router, authority) |
| `POST` | `/search/profiles` | Profile search — keyword/semantic/hybrid (authenticated) |
| `GET`  | `/search/exact` | Exact/partial name lookup (authenticated) |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | API status |
| `GET` | `/health` | Health check with timestamp |

---

## 🤖 AI Risk Classifier — Status & Honesty Notes

The risk classifier grades an SOS message into **LOW / MODERATE / HIGH / CRITICAL** with a
0–100 `risk_score`, matched risk `indicators`, and a `confidence`. It is designed as
**decision support for a human authority — never an automated dispatch trigger.** Every
result carries `is_demo_mode` and a plain-language `explanation`, and the AI verdict is
stored separately from any human decision (see the override endpoint) so the audit trail
always shows both.

### Swappable, tiered engine (`services/ml/`)

The engine picks the best backend installed, and **the API/frontend contract never changes**
when the model is swapped:

| Priority | Backend | Status | Requires | `is_demo_mode` |
|----------|---------|--------|----------|----------------|
| 1 | **DistilBERT** fine-tuned classifier | ⚙️ **FUTURE / pipeline ready** | `torch`+`transformers` + a model dir (`HAVEN_RISK_MODEL_DIR`) | `false` **only** if trained on real data and `HAVEN_RISK_PRODUCTION=1` |
| 2 | **scikit-learn** TF-IDF + LogisticRegression | 🧪 **DEMO (real ML, synthetic data)** | `scikit-learn`+`joblib`, a trained `.joblib` | `true` |
| 3 | **Rule-based lexicon** scorer | ✅ **IMPLEMENTED, always on** | nothing (pure stdlib) | `true` |

On a fresh checkout with no ML libraries, tier 3 runs — the app works out of the box.

### What is real vs. demo

- ✅ **IMPLEMENTED:** the rule-based classifier, the swappable engine, the human-in-the-loop
  override, `is_demo_mode` labeling, and a live evaluation harness.
- 🧪 **DEMO:** all metrics come from a **small synthetic dataset**
  (`services/ml/data/sos_risk_demo.jsonl`, ~80 rows). Real ML is used (sklearn / DistilBERT
  pipelines are functional), but numbers must **not** be cited as production performance.
- ⚙️ **FUTURE:** shipping a deployable DistilBERT model requires a large, representative,
  ethically-sourced labelled dataset and held-out validation from the same distribution.

**No metrics are hard-coded.** `ml/evaluate.py` runs the active backend live and prints
whatever precision/recall/F1 + confusion matrix actually result.

### Train / evaluate

```bash
cd haven/backend

# Evaluate the currently-active backend on the labeled demo set (runs with zero extra deps)
python ml/evaluate.py                 # full set
python ml/evaluate.py --test-split 0.25   # held-out split

# Optional: enable the trained tiers
pip install -r requirements-ml.txt
python ml/train_baseline.py           # -> services/ml/artifacts/sklearn_risk.joblib (auto-loaded)
python ml/train_distilbert.py --epochs 4   # -> a DistilBERT dir; set HAVEN_RISK_MODEL_DIR to enable

# Compare ALL installed backends side by side (rule → TF-IDF+LogReg → DistilBERT)
python ml/compare_backends.py                 # per-backend precision/recall/F1 + confusion matrix
python ml/compare_backends.py --test-split 0.25
```

`ml/compare_backends.py` runs every **available** backend over the same labeled examples and
prints a side-by-side comparison plus a confusion matrix each. Backends that are not installed
are clearly skipped (never faked). This is what lets you say: *"multiple interchangeable NLP
classification backends, evaluated with precision, recall, F1, and confusion matrices."*

Rule-based tier on the 80-row demo set (indicative, computed live — errs toward higher
severity, the safe direction for triage): **exact ≈ 0.70, within-1-band ≈ 0.96, macro-F1 ≈ 0.71.**
(sklearn / DistilBERT numbers are produced only once you install `requirements-ml.txt` and train.)

### Config (all optional)

| Env var | Purpose |
|---------|---------|
| `HAVEN_RISK_BACKEND` | Force `transformer` \| `sklearn` \| `rules` |
| `HAVEN_RISK_MODEL_DIR` | Path to a fine-tuned DistilBERT dir (enables tier 1) |
| `HAVEN_RISK_SKLEARN_PATH` | Path to a trained sklearn `.joblib` (defaults to `services/ml/artifacts/`) |
| `HAVEN_RISK_PRODUCTION` | `1` to let a real DistilBERT model report `is_demo_mode=false` |
| `HAVEN_RISK_LLM_ENRICH` | `1` to let the LLM refine the free-text explanation (never the severity/score) |

---

## 🔎 Semantic + Hybrid Case & Profile Search

Case & Profile Intelligence supports **three explicit search modes** over the existing
**MongoDB Atlas `$vectorSearch`** — no PostgreSQL/pgvector migration:

| Mode | How it works | When to use |
|------|--------------|-------------|
| **keyword** | Deterministic text/regex matching + term-overlap scoring | Precise name / phrase lookup |
| **semantic** | `embed(query)` → Atlas `$vectorSearch` (cosine) | Conceptual / paraphrased queries |
| **hybrid** | Deterministic blend: `0.4·keyword + 0.6·normalised-semantic`, stable tie-break on id | Best general recall+precision |

Exact/partial name lookup (`GET /search/exact`) is preserved unchanged for precise matching.

### Embedding service (`services/embeddings/`)

A stable one-line contract the rest of the app depends on:

```python
from services.embeddings import embed, embedding_info
vector = embed("tall male, aggressive, threatened with a knife")  # -> list[float] (768-dim)
```

Backend: Google **`gemini-embedding-001`** (768 dimensions). Status is tracked honestly and
surfaced at **`GET /ai/embedding-info`**:

- **ACTIVE** — key configured and the last call returned a real vector.
- **FALLBACK** — a call ran but returned the documented zero-vector (upstream error/quota);
  vector search is degraded.
- **DEMO** — no `GEMINI_API_KEY`; embeddings cannot run.

When embeddings are DEMO/FALLBACK, semantic & hybrid transparently **degrade to keyword**
and the response sets `"search_mode": "keyword_fallback"` + `"degraded": true`. We never
fake similarity when the model isn't running.

### Result shape

Every result is normalised to: `id`, `score`, `excerpt`, `severity`, `status`, `timestamp`,
`search_mode`, and a `match_label`. Semantic matches are labelled **"Semantically similar
case/profile"** — similarity is an investigative **lead**, never proof of guilt or identity.

### Endpoints & authorization

| Method | Endpoint | Access | Notes |
|--------|----------|--------|-------|
| `POST` | `/search/cases` | **Authority** | `{query, limit?, mode?}` — cases are sensitive; auth enforced server-side |
| `POST` | `/search/semantic` | **Authority** | Same as above (dedicated search router) |
| `POST` | `/search/profiles` | **Authority** | `{description\|query, limit?, mode?}` — profile intelligence is sensitive; authority/admin only |
| `GET`  | `/search/exact` | Authenticated user | Exact/partial name lookup (keyword) |
| `GET`  | `/ai/embedding-info` | Public (read-only) | Model + honest status, no secrets |

### Atlas index setup

Semantic mode needs two Atlas vector-search indexes (see `setup_indexes.py`):

- `casesIndex` on `sos_cases.embedding` (768-dim, cosine)
- `culpritIndex` on `culprits.description_embedding` (768-dim, cosine)

### Limitations

- Semantic quality depends on the Gemini embedding key and the Atlas indexes existing.
  Without them, search still works in **keyword_fallback** mode (clearly labelled).
- Hybrid weights are fixed heuristics, not learned; retrieval quality is **not** benchmarked —
  no Recall@K/MRR numbers are claimed because there is no labelled retrieval ground-truth set.

---

## ⚖️ RAG Legal Assistant

The Legal Assistant is **retrieval-augmented**: it retrieves verified legal passages
*before* generating, and answers only from what it found.

```
question → embed(query) → Atlas $vectorSearch (legalIndex) → filter weak matches
        → constrained context → LLM (Groq + Gemini fallback) → grounded answer + citations
```

Reuses existing infrastructure — the `services.embeddings` service, MongoDB Atlas
`$vectorSearch`, and the existing `call_groq` LLM utility. No duplicate AI clients.

### Legal document model (`legal_docs`)

Each stored chunk carries: `document_id`, `chunk_index`, `chunk_id`, `chunk_hash`, `title`,
`text`, `source_name`, `source_url`, `jurisdiction`, `section`, `verification_status`,
`embedding`, `embedding_model`, `document_version`, `created_at`, `updated_at`, `uploaded_by`.

### Ingestion & chunking (`services/legal_rag.py → ingest_document`)

- Text is cleaned (whitespace/newline normalisation, structure preserved).
- **Chunking is paragraph-aware**: whole paragraphs are packed up to ~1200 chars; an
  over-long paragraph is split on sentence boundaries with ~150-char overlap. Deterministic.
- Each chunk is embedded via `embed()` and stored with full metadata.
- **Deduplication:** a SHA-256 `chunk_hash` prevents re-embedding identical chunks on re-ingest.

### Retrieval, grounding & citations

- Only **verified** passages scoring ≥ `HAVEN_LEGAL_MIN_SCORE` (default 0.55) are used.
- The generation prompt constrains the model to the numbered context and **forbids inventing
  laws, sections, case names, or citations**.
- The response includes a **Sources** list built *only* from passages actually retrieved —
  title, section, relevance %, and source URL when available.

### Safety behaviors

- **No-context:** if nothing relevant is retrieved, the assistant returns an explicit
  "couldn't find enough verified source material" message and **does not call the LLM** —
  it never hallucinates an answer.
- **Embeddings unavailable:** retrieval transparently falls back to keyword matching
  (`retrieval_mode: "keyword_fallback"`); status is visible via `GET /ai/embedding-info`.
- **LLM unavailable:** the retrieved sources are still surfaced with a clear
  "answer service unavailable" message — never invented content.

### Endpoints & authorization

| Method | Endpoint | Access | Notes |
|--------|----------|--------|-------|
| `POST` | `/legal/query` | Public (auth optional) | Victims can query verified sources; user id captured if present |
| `POST` | `/legal/ingest` | **Admin only** | Structured document ingestion |
| `POST` | `/legal/upload-doc` | **Admin only** | Verified-PDF ingestion (text extracted then chunked) |
| `GET`  | `/legal/documents` | **Admin only** | List ingested documents |

Queries are audited by content **hash** (not plaintext) plus the retrieved document IDs,
retrieval mode, and generation status.

### Setup

1. Create an Atlas vector index `legalIndex` on `legal_docs.embedding` (768-dim, cosine).
2. Set `GEMINI_API_KEY` (embeddings) and `GROQ_API_KEY` (generation).
3. As an admin, ingest verified documents via `/legal/ingest` or `/legal/upload-doc`.

### Limitations (honest status)

- This is a **prototype / general-information** system, not verified production legal
  infrastructure. It is only as good as the documents an admin ingests.
- Answer quality depends on the embedding key, the `legalIndex`, and the ingested corpus.
- No retrieval-quality metrics (Recall@K/MRR) are claimed — there is no labelled evaluation set.
- It is **not** legal advice; the UI shows a standing disclaimer.

---

## 🎙 Voice SOS AI Pipeline

Extends the existing Voice SOS (safe-word workflow preserved) with an explicit AI pipeline:

```
voice → speech-to-text → transcript → emergency intent → existing risk classifier → SOS workflow
```

### Speech-to-text
Browser **Web Speech API** (`SpeechRecognition` / `webkitSpeechRecognition`) — already in the
Voice SOS page. The UI handles microphone permission, listening state, transcript state,
unsupported-browser detection, and recognition errors. Recognition confidence is passed to the
backend when available.

### Emergency intent detection (`services/intent_service.py`)
A lightweight, **explainable, deterministic rule classifier** built on the shared risk lexicon —
so intent "signals" line up with the risk classifier's indicators (no second model). Classes:
`EMERGENCY | POSSIBLE_EMERGENCY | NON_EMERGENCY | UNKNOWN`. Swappable to an LLM backend via
`HAVEN_INTENT_LLM=1` (falls back to rules on any error). **Low speech-recognition confidence
down-grades EMERGENCY → POSSIBLE_EMERGENCY and forces a human confirmation** — uncertain audio
never auto-escalates.

### Risk integration
The transcript flows into the **existing** `RiskClassifier` (`services/ml`) — the same
swappable risk-engine contract used elsewhere. No duplicate severity model.

### Endpoint
`POST /voice-sos/analyze` — body `{transcript, recognition_confidence?, case_id?}` — returns
`{transcript, intent{…}, risk{…}, risk_available, needs_confirmation, auto_action:false}`.
**This endpoint never triggers an SOS** — it is decision-support. The user reviews intent +
severity + indicators, then confirms; a human authority still owns the final case decision.

### Human-in-the-loop & existing workflow
The safe-word auto-trigger workflow is **preserved unchanged**. The AI card is additive: it
shows a `Listening → Transcript → Analyzing → Ready` pipeline and a `Send SOS` / `Cancel`
confirmation. When AI is unavailable, the UI says so and still allows a manual SOS.

### Privacy
**No raw audio is persisted.** Only text/metadata (transcript, intent, severity, risk score)
is optionally stored on the SOS event/case for authority context.

### Limitations
- Web Speech API accuracy varies by browser/OS/accent and is **not** available in all browsers
  (notably limited on Firefox); the UI degrades gracefully.
- Rule-based intent is a heuristic baseline — no accuracy metric is claimed.
- AI output is decision-support only and is clearly labelled DEMO.

### Endpoints reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/voice-sos/analyze` | Transcript → intent + risk (no auto-action) |

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────┐
│                   USER (Victim)                  │
└──────────────────────┬──────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │    Next.js Frontend      │
          │  SOS · Therapy · Legal  │
          └────────────┬────────────┘
                       │ REST API
          ┌────────────▼────────────┐
          │    FastAPI Backend       │
          │    Python + Uvicorn     │
          └──┬──────┬──────┬───────┘
             │      │      │
    ┌────────▼─┐ ┌──▼───┐ ┌▼────────────┐
    │  Groq    │ │Gemini│ │ HuggingFace │
    │ LLaMA 3.3│ │Flash │ │  FLUX.1     │
    └────────┬─┘ └──┬───┘ └┬────────────┘
             │      │      │
    ┌────────▼──────▼──────▼────────────┐
    │         MongoDB Atlas              │
    │  sos_cases · culprits · sessions  │
    │     + Vector Search Index         │
    └───────────────────────────────────┘
```

### SOS Image Flow

```
1. Keywords input
2. Groq LLM → full distress message
3. FLUX.1 → innocent looking image (PNG)
4. PIL LSB → encode message in pixel LSBs
5. Download encoded PNG
6. Post on social with #HavenSOS
7. Authority uploads image to dashboard
8. PIL LSB decode → extract message
9. Groq → analyse severity, location, needs
10. MongoDB → save case → response dispatched
```

### Panic Button Flow

```
Hold 3 seconds → GPS captured via browser API
→ Emergency message built with Google Maps link
→ WhatsApp opens pre-filled → User taps Send
→ Trusted contact receives GPS + alert
```

---

## 🔐 Security Notes

- All API keys are stored in `.env` — **never commit `.env` to git** (`.env` is gitignored)
- MongoDB connection uses Atlas with IP whitelisting
- Steganography uses LSB encoding — invisible to naked eye
- **Rotate all API keys** if they are ever exposed publicly

### Authentication & authorization model

- User-owned resources (privacy data, Voice SOS config/history, trusted contacts,
  case/evidence writes, location updates) **require authentication** and enforce
  ownership from the **verified token identity** — a body/query `user_id` is never
  trusted for authorization. Owners access their own data; authority/admin roles are
  allowed cross-user only where explicitly intended.
- An unverifiable token can **never** grant an elevated (authority/admin) role — the
  role is forced to `user`.
- `POST /ai/classify-risk` has two paths. Without a `case_id` it performs an
  **ephemeral** analysis (nothing persisted) and stays open — rate-limited — so
  anonymous SOS triage still works. With a `case_id` the AI verdict is **persisted**
  against that case, which **requires authentication and ownership**: the caller must
  own the case (or be authority/admin), ownership is read from the stored case, and a
  body-supplied `user_id` is never trusted. An unknown case returns 404. This closes the
  IDOR where any caller could write an AI analysis onto an unrelated case. The endpoint
  is rate-limited (30 req / 60s per client).
- `POST /encode` and `POST /decode` (LSB steganography) stay **anonymous** — they
  are part of the covert victim SOS flow, where the user is not signed in. They are
  hardened rather than authenticated: base64 is validated (invalid → `400`), input
  size is capped (`~11 MB` → `413`), and images are checked for
  decompression-bomb / non-image payloads via `Image.MAX_IMAGE_PIXELS` and Pillow
  `verify()` before any steganography work (unsafe/corrupt → `400`, oversized → `413`).
  Error responses never leak tracebacks or Pillow internals. Both are rate-limited
  (`20 req / 60s` per client).
- Intentionally anonymous emergency initiation (SOS case creation, Voice SOS trigger
  gated by the secret safe-word) is preserved; data *reads* are not anonymous.
- **Offline SOS queue (encrypted at rest).** Queued SOSes wait in IndexedDB when the
  device is offline. Because an abuser may have physical access to the device, the SOS
  **content** (message, GPS coordinates, decoded distress text, outgoing payload) is
  **never stored in plaintext**. It is sealed with **AES-256-GCM** using a per-device,
  **non-extractable** key generated by Web Crypto and held in a separate IndexedDB store —
  there is no hardcoded key and no key derived from a public constant. Only non-sensitive
  delivery metadata (opaque UUID / idempotency key, status, retry count, timestamps) is in
  the clear, so idempotency and honest delivery states are preserved. Permanently `failed`
  items are retained for a bounded window (24h) then purged; pending/retryable items are
  never purged. `wipeQueue()` clears all records and destroys the key so any residual
  ciphertext becomes unrecoverable — the integration point for a future duress wipe.
  **Residual limitation:** a non-extractable key still lets the *same browser profile*
  decrypt (the app must be able to resend), so this protects against offline/forensic
  extraction of storage, not against code running in an already-unlocked browser.
- The live-GPS WebSocket `/ws/track/{event_id}` verifies the token and authorizes it
  against the event: only the event owner may broadcast coordinates; only the owner or
  an authority/admin may subscribe. Unauthorized/expired/missing tokens are rejected.
- **Individual authority credentials (no shared password).** Authority login is per
  officer, not a single shared portal password. Each officer has a server-side record in
  the `authority_accounts` collection (`authority_id`, `badge_number`, `officer_name`,
  PBKDF2 `password_hash` + `password_salt`, `role`, `active`, timestamps). Login accepts a
  `badge_number` (the officer's username) + individual `password`; the server looks up the
  record, verifies the password against the stored hash, and checks the account is active.
  **The authenticated identity embedded in the token (user_id / name / role) is read
  entirely from the verified record — never from client-supplied `officer_name`, `station`,
  `role`, or `actor_id` fields.** Passwords are hashed verbatim with PBKDF2-HMAC-SHA256
  (100k iterations, per-record 16-byte salt) and additionally bound to a server-side
  **pepper** (`AUTHORITY_SECRET_KEY`), so a database leak alone cannot be attacked offline.
  Login stays rate-limited at `5 req / 60s`. Provision accounts with the operator CLI
  (there is intentionally **no public provisioning endpoint**):

  ```bash
  cd haven/backend
  python provision_authority.py --badge PO-1091 --name "Insp. Rao"        # prompts for password
  python provision_authority.py --badge PO-1091 --deactivate               # disable an account
  ```

  In **non-production**, a single local dev authority is auto-seeded on first login
  (badge `PO-1091`, password `haven2024`, overridable via `DEV_AUTHORITY_*`) so the app
  runs out of the box. This dev bootstrap is hard-disabled when `ENVIRONMENT=production`;
  production **must** provision individual accounts explicitly, and there is no universal
  production password. **Residual limitation:** account provisioning is operator-run (no
  self-service password reset / rotation UI yet), and `AUTHORITY_SECRET_KEY` rotation
  requires re-hashing existing passwords.
- **Admin role changes are now persisted (P1-8).** `PATCH /admin/users/{id}/role`
  previously validated, audited and returned success but never wrote the change, so
  RBAC silently stayed on the old role. It now performs an atomic single-identity update
  of the `role` field in the authoritative `authority_accounts` store (the only durable,
  login-consulted role field in HAVEN) — never upserting, so an unknown id returns `404`
  and no unrelated fields are touched. Admin-only (`require_admin`); the acting-admin
  identity comes from the verified token, never the request body. An admin cannot demote
  their own admin account (lockout safety). **Token/session note:** roles are JWT claims
  baked at login, so a persisted change applies on the target's **next login**; existing
  sessions keep their current role until re-authentication — the response says so
  (`effective_immediately: false`). **Limitation:** this manages provisioned authority
  identities; normal Clerk users have no durable role record and are always "user" by
  design (unverified tokens are never elevated), so promoting a brand-new person to
  authority is done by provisioning an authority account (`provision_authority.py`).
- **Audit logging is request-aware and tamper-evident (P2-1).** `log_audit` now
  captures the real client IP and a truncated user-agent when a `Request`/`WebSocket`
  is passed, reusing HAVEN's existing trusted IP handling (`rate_limiter.get_client_ip`,
  which honours the app's established `X-Forwarded-For` first-hop assumption, else the
  direct peer) rather than a new proxy scheme. Sensitive access that previously had no
  trail is now recorded: `PRIVACY_DATA_ACCESSED` on `/privacy/my-data/{user_id}` (after
  authorization; actor + target + counts only, **never the returned PII**), and
  `WS_CONNECTED` / `WS_CONNECT_REJECTED` / `WS_DISCONNECTED` on `/ws/track/{event_id}`
  (identity from the verified token, event_id and outcome only — **never live GPS
  coordinates**). Each new record is linked into a SHA-256 hash chain
  (`event_hash = SHA256(previous_hash + canonical_event_json)`; `verify_audit_chain`
  detects any later edit or broken link). The legal-query content-hash approach is
  preserved. **This is tamper *evidence*, not WORM:** a privileged database
  administrator could still rewrite the whole chain — application-level hashing only
  makes single-record edits detectable, and the global chain has a documented
  concurrency limitation. Legacy records without `ip_address`/`previous_hash`/
  `event_hash` remain fully readable (verifier skips un-chained rows). Authorization,
  RBAC and JWT handling are unchanged.

- **Rate limiting and security cooldowns can now be distributed (P2-2).** The limiter
  (`rate_limiter.py`) keeps its exact caller interface —
  `Depends(rate_limit_dependency(max_requests=…, window_seconds=…))` — and now decides
  *internally* whether to enforce limits in a shared **Redis** backend or the original
  in-memory `SlidingWindowRateLimiter`. When `REDIS_URL`/`REDIS_ENABLED` are configured
  and the optional `redis` package is reachable, limits use an **atomic Lua sliding-window
  script** (prune → count → conditional add + expire in a single execution, so there is no
  GET→increment→SET race), keyed `haven:ratelimit:<endpoint-scope>:<identity>`. Each
  endpoint gets its own bucket (no single global bucket), and identity is the trusted
  client IP plus a **SHA-256 digest of the Authorization header — never the raw JWT**.
  The 429 body (`"Rate limit exceeded. Maximum N requests per W seconds."`) and
  `Retry-After: W` header are unchanged. The **voice-SOS cooldown** is now durable across
  restarts and instances via `haven:cooldown:voice_sos:<user_id>` TTL keys (per-user
  keyed, so one user's cooldown never blocks another's SOS). **Failure policy:**
  rate-limited endpoints **fail closed (HTTP 503)** when `REDIS_REQUIRED_IN_PRODUCTION`
  is set and Redis is missing/unreachable — they never silently degrade to unbounded
  single-process limits; security **cooldowns never fail closed** and fall back to the
  in-memory mirror, because blocking a legitimate emergency on an infra outage is worse
  than a locally-scoped cooldown. Local development needs no Redis and behaves exactly as
  before (single-process in-memory). See `REDIS_URL` / `REDIS_ENABLED` /
  `REDIS_REQUIRED_IN_PRODUCTION` in `backend/.env.example`, and the optional `redis`
  Python package in `requirements.txt`. To use Redis locally, install and run a native
  Redis service (`redis-server`, or Memurai / WSL on Windows) and point `REDIS_URL` at
  `redis://localhost:6379/0`.

- **Authentication errors are sanitized and request bodies are globally bounded (P2-3).**
  Every client-visible auth failure now returns a single stable body — `401
  {"detail": "Invalid or expired authentication token"}` — regardless of the
  underlying cause (malformed token, bad signature, expired token, missing claims,
  or a failed Clerk/JWKS verification). Raw JWT-library exception text, issuer
  details, key IDs, JWKS URLs and signing configuration are **never** returned to
  the client; the reason category is logged internally only (never the token,
  password, secret or key). Status codes and authority/admin authorization
  semantics are unchanged (401 stays 401, 403 stays 403). Separately, a pure-ASGI
  `BodySizeLimitMiddleware` rejects oversized HTTP requests with **413** at the app
  boundary *before* any route runs: it fast-rejects an honest oversized
  `Content-Length` and also **counts streamed bytes**, so a spoofed/absent
  `Content-Length` or chunked transfer-encoding request is still bounded (the
  middleware never buffers the whole body). WebSocket and lifespan scopes pass
  through untouched, and GET/HEAD with no body are unaffected. The global ceiling
  (`MAX_REQUEST_BODY_BYTES`, default **50 MB**) is sized for the largest legitimate
  request — the `/sos/evidence` upload (`audio_base64` + `image_base64` up to 20 MB
  each) — while the stricter per-endpoint limits stay in force (legal PDF 15 MB,
  media 10 MB, covert stego image ~11 MB). In **production** an unlimited/0/invalid
  value is rejected at boot (fail-fast). See `MAX_REQUEST_BODY_BYTES` in
  `backend/.env.example`.

### Production configuration (fail-closed)

Set `ENVIRONMENT=production`. The backend **refuses to start** if any of these are
missing or left at their insecure development defaults:

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET` | Signs Haven-internal tokens |
| `AUTHORITY_SECRET_KEY` | Server-side pepper for authority password hashing |
| `EVIDENCE_ENCRYPTION_KEY` | AES-256-GCM evidence key |
| `CLERK_ISSUER` | Clerk issuer (enables RS256 verification) |
| `CLERK_JWKS_URL` | Clerk JWKS endpoint |

In production `STRICT_AUTH` defaults to **true**, so unverifiable tokens are rejected
(no fallback to decoding unverified JWT claims). Local development keeps the documented
`.env.example` defaults so the app runs out of the box.

### ⚠️ Previously committed credentials must be rotated

Real **Clerk** and **ElevenLabs** credentials were committed to this repository's git
history (in a `.env.local.example` that has since been sanitized). **Removing the files
alone does not invalidate credentials already exposed in git history.** These
credentials must be treated as compromised and **rotated at their providers**:

- **Clerk** — rotate the secret key (and publishable key) in the Clerk dashboard, then
  update the deployment env. (The exposed key is not reproduced here.)
- **ElevenLabs** — regenerate the API key in the ElevenLabs account settings.

History rewriting (e.g. `git filter-repo`/BFG) is **not** performed automatically; rotate
first, then optionally purge history. Until rotation, assume the old keys are usable by
anyone who has seen the history.

---

## 🚨 Emergency Contacts (India)

| Number | Service |
|--------|---------|
| **112** | National Emergency |
| **181** | Women's Helpline |
| **1091** | Domestic Violence Helpline |
| **15100** | NALSA Free Legal Aid |
| **7827170170** | NCW Helpline |
| **9152987821** | iCALL Counseling |

---

## 🗺️ Roadmap

- [ ] Multi-region deployment (India + global)
- [ ] SMS fallback for SOS when internet unavailable  
- [ ] Fine-tune LLM on Indian domestic abuse legal corpus
- [ ] Offline PWA mode for low-connectivity areas
- [ ] Multi-tenant architecture for NGO partners
- [ ] DPDP Act (India) compliance audit
- [ ] Hashtag auto-monitoring system for #HavenSOS
- [ ] Voice-to-SOS (speak keywords, no typing needed)

---

## 👥 Team

**Team Byte Me** 

Built with ❤️ for women's safety · AI for Social Good

---

## 📄 License

This project is built for hackathon purposes. All cited laws are real Indian statutes. Legal information is for educational purposes — consult a qualified lawyer for specific legal advice.

---

<div align="center">

*"Because every woman deserves a voice — even in silence."*

**🛡️ HAVEN**

</div>
