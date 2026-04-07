# 01 — Project Overview

## What Is This Project?

StudyRAG is a web application that turns university study materials into an intelligent, conversational assistant. Students upload PDFs — lecture notes, past exam papers, and syllabus documents — and then ask questions in plain language. The system finds relevant passages from those documents and uses a large language model (Gemini) to write a coherent answer citing its sources.

**Key promise:** Every answer comes only from the uploaded documents. The AI never invents facts or reaches for general internet knowledge.

---

## What Problem Does It Solve?

When preparing for exams, students typically:
- Hunt through hundreds of pages of notes to find a definition
- Flip through old question papers asking "has this topic appeared before?"
- Try to map syllabus unit topics to relevant questions

StudyRAG automates all three. You ask "explain TCP/IP", or "what questions came from unit 3 of Data Communications in the university exam?", and the system finds the answer for you across all uploaded materials.

---

## Key Concepts (Plain English)

### Retrieval-Augmented Generation (RAG)

RAG is a two-step process:

1. **Retrieve** — When a student asks a question, find the most relevant paragraphs from the uploaded documents.
2. **Generate** — Give those paragraphs to a language model along with the question, and let it write a clear answer.

This is different from asking ChatGPT directly. ChatGPT guesses from its training data. RAG forces the model to only use the text you gave it, so you can trace every claim back to a source.

> **Learn more:** [What is RAG? (IBM)](https://www.ibm.com/topics/retrieval-augmented-generation)

### Vector Embeddings

To find "relevant" paragraphs, the system converts every piece of text into a list of ~3000 numbers called an **embedding**. Similar texts produce similar number lists. When a question arrives, it is also converted to numbers, and the database finds the text chunks whose numbers are closest.

Think of it as: every text chunk is a point in a 3072-dimensional space. Finding relevant chunks = finding nearby points.

> **Learn more:** [Vector Embeddings (Cloudflare)](https://www.cloudflare.com/learning/ai/what-are-embeddings/)

### pgvector

pgvector is a PostgreSQL extension that adds a new column type — `vector(3072)` — and lets you run fast "nearest neighbour" queries using the `<=>` operator (cosine distance). This avoids needing a separate vector database.

> **Learn more:** [pgvector GitHub](https://github.com/pgvector/pgvector)

### Google Vertex AI / Gemini

The project uses Google's Gemini language models via Vertex AI:
- **gemini-2.5-pro** — the large model, used for structured extraction (reading exam papers) and writing final answers
- **gemini-2.5-flash** — the small/fast model, used for intent classification, summary, and subject detection
- **gemini-embedding-001** — converts text to 3072-dimensional vectors

Vertex AI is Google's managed cloud service for running these models. You pay per token (unit of text processed).

> **Learn more:** [Google Vertex AI Overview](https://cloud.google.com/vertex-ai/docs/start/introduction-unified-platform)

### Celery (Task Queue)

Processing a PDF takes 30–120 seconds (text extraction, OCR, multiple Gemini API calls, embedding). A user should not have to wait — they upload the file and come back later.

Celery solves this by putting the work in a **queue** (backed by Redis). A separate worker process picks up jobs from the queue and runs them in the background. The web server stays responsive.

> **Learn more:** [Celery Docs](https://docs.celeryq.dev/en/stable/getting-started/introduction.html)

### Google Cloud Storage (GCS)

Uploaded PDFs are stored in GCS (Google's equivalent of AWS S3). The database only stores the `gcs_key` (path) pointing to the file. When a Celery worker needs to process the file, it downloads it from GCS.

---

## Technology Stack

### Backend
| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web framework | FastAPI (Python) | HTTP API, async request handling |
| ORM | SQLAlchemy 2 (async) | Database access |
| Database | PostgreSQL 15 + pgvector | Stores everything including vectors |
| Task queue | Celery 5 + Redis | Background document processing |
| AI models | Google Gemini via Vertex AI | Text generation + embeddings |
| File storage | Google Cloud Storage | Stores uploaded PDFs |
| Auth | JWT (python-jose) + bcrypt | Token-based authentication |
| Caching | Redis | Response cache, rate limiting |
| Logging | structlog | JSON-structured logs |

### Frontend
| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | React 18 + TypeScript | UI components |
| Routing | React Router v6 | Page navigation |
| State | Zustand | Auth state, chat state |
| HTTP client | Axios | API calls |
| Styling | Tailwind CSS | Utility-first CSS |
| Markdown | react-markdown + remark-gfm | Rendering AI responses |
| Streaming | Fetch API + SSE | Token-by-token streaming display |

---

## Document Types

The system handles three types of documents:

| Type | Value in DB | What it contains | How it's processed |
|------|------------|-----------------|-------------------|
| Lecture Notes | `notes` | PDF or text of course notes | Chunked per page, embedded, stored in `notes` table |
| University Exam | `university_exam` | Past exam question papers | Questions extracted by Gemini Pro, one chunk per question, stored in `document_chunks` |
| Syllabus | `syllabus` | Course syllabus with unit/topic breakdown | Per-subject structured extraction (subject code, units, topics), stored in `syllabus` table |

---

## User Roles

| Role | What they can do |
|------|----------------|
| `student` | Chat only — ask questions, view conversation history |
| `staff` | Chat + upload documents |
| `admin` | Everything: chat, upload, user management, view all conversations |

---

## Project Directory Structure

```
rag-app/
├── backend/                    # Python FastAPI backend
│   ├── app/
│   │   ├── api/v1/             # HTTP endpoints
│   │   │   └── endpoints/
│   │   │       ├── auth.py     # Register, login, refresh token
│   │   │       ├── chat.py     # Conversations, RAG queries, streaming
│   │   │       ├── documents.py # Upload, status, list, delete
│   │   │       └── admin.py    # User management, stats
│   │   ├── core/
│   │   │   ├── config.py       # All settings (loaded from .env)
│   │   │   ├── rate_limiter.py # SlowAPI rate limits
│   │   │   └── exceptions.py   # Global error handlers
│   │   ├── db/
│   │   │   ├── models/models.py # SQLAlchemy ORM models
│   │   │   └── session.py      # Async engine + session factory
│   │   ├── schemas/schemas.py  # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── auth/           # JWT, password hashing, RBAC
│   │   │   ├── ingestion/      # PDF extraction, chunking, embedding
│   │   │   │   ├── extractor.py      # PyMuPDF + Vision OCR
│   │   │   │   ├── exam_processor.py # Gemini Pro structured extraction
│   │   │   │   ├── notes_processor.py # Page-level chunking
│   │   │   │   ├── syllabus_processor.py # Multi-subject extraction
│   │   │   │   ├── chunker.py        # Text splitting strategies
│   │   │   │   ├── vector_store.py   # pgvector upsert/search
│   │   │   │   └── gcs_service.py    # GCS upload/download
│   │   │   ├── llm/
│   │   │   │   └── gemini_client.py  # Gemini SDK wrapper
│   │   │   ├── rag/
│   │   │   │   └── pipeline.py       # 6-intent RAG pipeline
│   │   │   └── session/
│   │   │       └── session_service.py # Conversations, short-term memory
│   │   ├── tasks/
│   │   │   └── celery_app.py   # Background task definitions
│   │   ├── utils/
│   │   │   └── cache.py        # Redis cache wrapper
│   │   └── main.py             # FastAPI app factory, startup events
│   ├── alembic/                # Database migration scripts
│   ├── scripts/
│   │   └── seed_admin.py       # Creates first admin user
│   └── requirements.txt
├── frontend/                   # React TypeScript frontend
│   └── src/
│       ├── App.tsx             # Routes
│       ├── pages/
│       │   ├── LoginPage.tsx
│       │   ├── RegisterPage.tsx
│       │   ├── ChatPage.tsx    # Main chat + upload modal
│       │   └── AdminPage.tsx
│       ├── store/
│       │   ├── authStore.ts    # Zustand: user, login, logout
│       │   └── chatStore.ts    # Zustand: conversations, messages, streaming
│       └── services/
│           ├── api.ts          # Axios instance with token interceptor
│           └── apiService.ts   # Typed wrappers for every endpoint
└── docs/                       # This documentation
```
