
# 🛡️ HAVEN — A Silent Shield, A Strong Voice

<div align="center">

![Haven Banner](https://img.shields.io/badge/HAVEN-AI%20for%20Social%20Good-be185d?style=for-the-badge&logo=shield&logoColor=white)
![Hacknovate](https://img.shields.io/badge/Hacknovate-7.0-6d1f3e?style=for-the-badge)
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
pip install fastapi uvicorn pymongo python-dotenv requests \
            Pillow google-generativeai pypdf cloudinary
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

```bash
cd haven/backend
uvicorn backend.main:app --reload
# Server runs at http://localhost:8000
```

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

### Cases & Authority

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/cases` | Get all SOS cases (filter by severity/status) |
| `POST` | `/save-extracted-data` | Save decoded SOS to MongoDB |
| `PATCH` | `/cases/{case_id}` | Update case status |

### Culprit Database

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/culprit/report` | Register culprit profile with embedding |
| `POST` | `/culprit/find-match` | Search by name or AI vector similarity |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | API status |
| `GET` | `/health` | Health check with timestamp |

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

- All API keys are stored in `.env` — **never commit `.env` to git**
- MongoDB connection uses Atlas with IP whitelisting
- Steganography uses LSB encoding — invisible to naked eye
- No user authentication stored — sessions are anonymous for safety
- **Rotate all API keys** if they are ever exposed publicly

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

**Team Byte Me** — Hacknovate 7.0

Built with ❤️ for women's safety · AI for Social Good

---

## 📄 License

This project is built for hackathon purposes. All cited laws are real Indian statutes. Legal information is for educational purposes — consult a qualified lawyer for specific legal advice.

---

<div align="center">

*"Because every woman deserves a voice — even in silence."*

**🛡️ HAVEN**

</div>
