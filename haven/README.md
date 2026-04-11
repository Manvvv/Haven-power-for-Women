# 🌸 Haven — Clone Setup Guide

> *A Silent Shield. A Strong Voice.*  
> AI-powered platform for women in abusive situations — built without AWS Bedrock or S3.

---

## 🔄 What Changed from the Original

| Original (AWS) | This Clone (Free) | Notes |
|---|---|---|
| AWS Bedrock (Titan Text) | **Google Gemini 1.5 Flash** | Free: 1,500 req/day |
| AWS Bedrock (Embeddings) | **Gemini text-embedding-004** | Free: 1,500 req/day |
| AWS Titan Image Generator | **HuggingFace SDXL** | Free inference API |
| AWS S3 Storage | **Cloudinary** | Free: 25 GB/month |
| Groq inference | **Groq** (same) | Free tier |

---

## 🏗️ Architecture

```
haven/
├── backend/              # Python 3.12 + FastAPI
│   ├── main.py           # All 15 API endpoints
│   ├── setup_indexes.py  # One-time MongoDB Atlas index setup
│   ├── requirements.txt
│   └── .env.example      # Copy → .env and fill in keys
│
└── frontend/             # Next.js 14 + TypeScript + Tailwind
    ├── src/app/
    │   ├── page.tsx           # Landing page
    │   ├── sos/page.tsx       # 4-step SOS steganography flow
    │   ├── therapy/page.tsx   # AI therapy chat + ElevenLabs TTS
    │   ├── legal/page.tsx     # Legal RAG chatbot
    │   ├── authority/page.tsx # Officer dashboard
    │   ├── dashboard/page.tsx # User home after login
    │   └── sign-in / sign-up  # Clerk auth
    ├── src/middleware.ts      # Route protection
    └── .env.local.example     # Copy → .env.local and fill in keys
```

---

## 🔑 API Keys You Need (All Free Tiers)

### 1. MongoDB Atlas (Database + Vector Search)
- Go to: https://www.mongodb.com/atlas/database
- Create a **free M0 cluster**
- Add your IP to the allowlist
- Create a database user
- Copy the connection string → `MONGO_ENDPOINT`

### 2. Google Gemini (Text Generation + Embeddings)
- Go to: https://aistudio.google.com/app/apikey
- Create an API key → `GEMINI_API_KEY`
- Free: 1,500 requests/day, 1M tokens/min

### 3. Groq (Fast LLM Inference)
- Go to: https://console.groq.com
- Create a free account → API Keys → `GROQ_API_KEY`
- Free tier: very generous limits, uses Llama 3

### 4. Cloudinary (Image Storage — replaces S3)
- Go to: https://cloudinary.com (sign up free)
- Dashboard → API Keys
- Copy Cloud Name, API Key, API Secret
- Free: 25 GB storage + 25 GB bandwidth/month

### 5. HuggingFace (Image Generation — replaces Bedrock Titan)
- Go to: https://huggingface.co/settings/tokens
- Create a token (read access is fine) → `HF_API_KEY`
- Free inference API (may be slow, ~20–30s per image)

### 6. Clerk (Authentication)
- Go to: https://clerk.com
- Create a new application
- Copy Publishable Key and Secret Key
- Free tier: up to 10,000 monthly active users

### 7. ElevenLabs (Text-to-Speech for Therapy Bot)
- Go to: https://elevenlabs.io
- Create free account → Profile → API Key
- Free: 10,000 characters/month
- Optional — voice will be silent if not set

---

## 🚀 Local Setup

### Backend

```bash
# 1. Create and activate virtual environment
cd haven
python -m venv .venv

# Windows:
.venv\Scripts\Activate
# Mac/Linux:
source .venv/bin/activate

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Set up environment variables
cp backend/.env.example backend/.env
# Edit backend/.env and fill in all keys

# 4. Set up MongoDB indexes (run ONCE)
python backend/setup_indexes.py

# 5. Start the API server
uvicorn backend.main:app --reload
# → API available at http://localhost:8000
# → Docs at http://localhost:8000/docs
```

### Frontend

```bash
# 1. Install packages
cd frontend
npm install

# 2. Set up environment variables
cp .env.local.example .env.local
# Edit .env.local and fill in all keys

# 3. Start dev server
npm run dev
# → App at http://localhost:3000
```

---

## 📋 All Backend Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/text-generation` | Expand keywords into full distress message |
| POST | `/img-generation` | Generate innocent-looking image (HuggingFace SDXL) |
| POST | `/encode` | Hide message inside image (LSB steganography) |
| POST | `/decode` | Extract hidden message from image |
| POST | `/text-decomposition` | Parse decoded message into structured fields |
| POST | `/save-extracted-data` | Save SOS case to MongoDB |
| GET | `/cases` | List cases (filter by severity/status) |
| PATCH | `/cases/{case_id}` | Update case status |
| POST | `/culprit/report` | Register culprit + generate embedding |
| POST | `/culprit/find-match` | Find similar profiles (vector search) |
| POST | `/legal/query` | Legal RAG question answering |
| POST | `/legal/upload-doc` | Upload + embed PDF for legal knowledge base |
| POST | `/therapy/chat` | Therapy conversation with session memory |
| POST | `/upload-image` | Upload image to Cloudinary |
| POST | `/generate-poem` | Generate empowering poem |

---

## 🧠 How the Features Work

### 1. Discreet SOS (Steganography)
User types keywords → Gemini expands to full message → HuggingFace generates innocent image → LSB steganography hides message in pixel data → User shares image on social media with `#HavenSOS` → Authority decodes image → Groq decomposes text → Case saved to MongoDB

### 2. Therapy Bot
User types → Groq Llama 3 70B generates empathetic response → ElevenLabs converts to speech → Played in browser via Web Audio API → Session history stored in MongoDB per user

### 3. Legal RAG Bot
PDFs uploaded → PyPDF extracts text → Chunked into 500-char pieces → Gemini generates 768-dim embeddings → Stored in MongoDB Atlas Vector Search → User asks question → Question embedded → Vector search retrieves top 5 relevant chunks → Groq generates answer grounded in retrieved law

### 4. Culprit Matching
Authority reports physical + behavioral traits → Gemini embeds description → Stored in MongoDB with vector index → Another officer searches with new description → Vector similarity search returns top N matches by cosine distance

---

## 🌐 Deployment

### Backend → Render (Free)
1. Push to GitHub
2. Create a new **Web Service** on https://render.com
3. Set build command: `pip install -r backend/requirements.txt`
4. Set start command: `uvicorn backend.main:app --host 0.0.0.0 --port 10000`
5. Add all environment variables from `.env`

### Frontend → Vercel (Free)
1. Push frontend/ to GitHub (or a subdirectory)
2. Import project at https://vercel.com
3. Set root directory to `frontend`
4. Add all environment variables from `.env.local`
5. Deploy

---

## ⚠️ Important Notes

- **Not a substitute for emergency services.** Always include hotline numbers prominently.
- **MongoDB Atlas M0 is free** but has limited storage (~512 MB). Sufficient for a demo.
- **HuggingFace free tier** may have cold-start delays (30–60s first request). Consider upgrading for production.
- **Steganography** in this implementation uses LSB encoding. The image must be PNG (not JPEG, which uses lossy compression that destroys hidden data).
- **Vector search** requires MongoDB Atlas M10+ for production vector indexes. M0 clusters have limited support — the code falls back to recent records gracefully.

---

## 🆘 Emergency Contacts (India)

| Service | Number |
|---|---|
| Emergency | 112 |
| Women's Helpline | 181 |
| Domestic Violence | 1091 |
| Police | 100 |
| iCall Counseling | 9152987821 |
| NALSA Legal Aid | 15100 |
| NCW | 7827170170 |
| Childline | 1098 |
