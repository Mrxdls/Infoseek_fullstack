# StudyRAG — Production-Grade RAG Application

A full-stack, production-ready Retrieval-Augmented Generation system for educational document Q&A.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                               │
│   React SPA (Tailwind, Zustand, React Query, SSE Streaming)        │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTPS / WSS
┌───────────────────────────▼─────────────────────────────────────────┐
│                        API LAYER                                    │
│   FastAPI  ·  JWT Auth (RS256)  ·  SlowAPI Rate Limiting           │
│   /auth  /documents  /chat  /admin                                  │
└──────────┬──────────────────────────────────────┬───────────────────┘
           │ Async SQLAlchemy                      │ Celery task.delay()
┌──────────▼──────────┐              ┌─────────────▼────────────────┐
│   PostgreSQL 15      │              │   Celery Worker              │
│   - users            │              │   - process_document         │
│   - documents        │              │     ├─ S3 download           │
│   - chunks           │              │     ├─ text extraction       │
│   - conversations    │              │     ├─ OCR (Vision API)      │
│   - messages         │              │     ├─ AI exam parsing       │
└──────────────────────┘              │     ├─ chunking strategy     │
                                      │     ├─ batch embedding       │
┌─────────────────────┐               │     └─ Qdrant upsert        │
│   Redis              │◄─────────────┤                              │
│   - Celery broker    │              │   Celery Beat (scheduled)    │
│   - result backend   │              │   - expire_stale_sessions    │
│   - query cache      │              └──────────────────────────────┘
└─────────────────────┘
                                      ┌──────────────────────────────┐
                                      │   Qdrant Vector DB           │
                                      │   - cosine similarity        │
                                      │   - MMR retrieval            │
                                      │   - payload filtering        │
                                      └──────────────────────────────┘
                                      ┌──────────────────────────────┐
                                      │   AWS S3                     │
                                      │   - original documents       │
                                      │   - pre-signed URLs          │
                                      └──────────────────────────────┘
```

---

## RAG Pipeline Flow

```
User Query
    │
    ▼
[1] Intent Classification (small model: gpt-3.5-turbo)
    ├── off_topic → Refuse with canned response
    ├── unsafe   → Refuse with canned response
    └── educational / follow_up → Continue
    │
    ▼
[2] Query Rewriting (follow_up only — small model)
    "What about its types?" → "What are the types of normalization in DBMS?"
    │
    ▼
[3] Embed Query  (text-embedding-ada-002)
    │
    ▼
[4] MMR Retrieval from Qdrant
    ├── Fetch 3× top_k candidates
    ├── Apply priority boosting (exam questions scored higher)
    ├── MMR selection (λ=0.5, balance relevance vs diversity)
    └── Deduplication (>95% text overlap removed)
    │
    ▼
[5] Prompt Construction
    ├── System prompt (strict grounding rules)
    ├── Conversation summary (long-term memory)
    ├── Recent messages (short-term memory, last 10)
    └── Retrieved chunks with source labels
    │
    ▼
[6] LLM Generation (large model: gpt-4o)
    │
    ▼
[7] Post-generation Guardrails
    └── System prompt leak detection
    │
    ▼
Response + Sources → Frontend
```

---

## Document Ingestion Pipeline

```
Upload (PDF / DOCX / TXT / MD)
    │
    ▼
Store in S3  →  Create DB record  →  Dispatch Celery task
    │
    ▼  (Celery Worker)
Detect file type
    ├── PDF: Try PyMuPDF digital extraction
    │       avg_chars/page < 50 → OCR (Google Vision API)
    ├── DOCX: python-docx
    └── TXT/MD: plain decode
    │
    ▼
Clean & Normalize text
    │
    ▼
Document Type?
    ├── Exam Paper → AI Parse (small model)
    │               Extract: subject_name, subject_code, questions
    │               Chunking: Per-question with metadata prefix
    │               "[Subject: DBMS | Code: CS301]\nQ1: Explain..."
    │
    ├── Learning Material → Structure-aware chunking
    │                       Split at headings, paragraphs
    │
    └── OCR Result → Tight chunking (256 tok, 64 overlap)
    │
    ▼
Batch Embed (OpenAI ada-002)  →  Upsert to Qdrant
    │
    ▼
Save chunks to PostgreSQL  →  Update document status: INDEXED
```

---

## DB Schema

```sql
users           (id, email, hashed_password, full_name, role, is_active, ...)
refresh_tokens  (id, user_id → users, token_hash, expires_at, revoked)
documents       (id, uploaded_by_id → users, s3_key, document_type, status,
                 subject_name, subject_code, page_count, task_id, ...)
document_chunks (id, document_id → documents, chunk_index, chunk_text,
                 subject_name, subject_code, document_type, priority,
                 qdrant_point_id, token_count, chunk_metadata)
conversations   (id, user_id → users, session_type, title, summary,
                 session_id, is_active, expires_at)
messages        (id, conversation_id → conversations, role, content,
                 retrieved_chunk_ids, model_used, token_count, latency_ms)
```

---

## Folder Structure

```
rag-app/
├── docker-compose.yml        # All services
├── .env.example              # Environment template
├── Makefile                  # Dev commands
├── scripts/
│   └── seed_admin.py         # Create first admin
├── docker/
│   └── init.sql              # PostgreSQL init
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements-test.txt
│   ├── pytest.ini
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/         # Migration files (generated)
│   └── app/
│       ├── main.py           # FastAPI app factory
│       ├── core/
│       │   ├── config.py     # Pydantic settings
│       │   ├── exceptions.py # Global exception handlers
│       │   ├── logging.py    # Structured logging (structlog)
│       │   └── rate_limiter.py
│       ├── db/
│       │   ├── session.py    # Async SQLAlchemy engine
│       │   ├── models/
│       │   │   └── models.py # All ORM models
│       │   └── repositories/ # (extensible — add repo pattern here)
│       ├── schemas/
│       │   └── schemas.py    # All Pydantic request/response schemas
│       ├── api/v1/
│       │   ├── router.py     # Aggregated API router
│       │   └── endpoints/
│       │       ├── auth.py       # Register, login, refresh, /me
│       │       ├── documents.py  # Upload, status, list, delete
│       │       ├── chat.py       # Conversations, query, stream
│       │       └── admin.py      # User management, stats
│       ├── services/
│       │   ├── auth/
│       │   │   └── auth_service.py  # JWT, RBAC, token rotation
│       │   ├── ingestion/
│       │   │   ├── s3_service.py    # S3 upload/download
│       │   │   ├── extractor.py     # PDF/DOCX/TXT/OCR extraction
│       │   │   ├── chunker.py       # Strategy-based chunking
│       │   │   └── vector_store.py  # Qdrant MMR retrieval
│       │   ├── rag/
│       │   │   └── pipeline.py  # Full RAG pipeline
│       │   └── session/
│       │       └── session_service.py  # Context & memory mgmt
│       ├── tasks/
│       │   └── celery_app.py    # Celery app + all tasks
│       └── utils/
│           └── cache.py         # Redis cache service
│
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── tailwind.config.js
    └── src/
        ├── App.tsx               # Router root
        ├── index.tsx             # React entry point
        ├── index.css             # Tailwind + global styles
        ├── components/
        │   └── ProtectedRoute.tsx
        ├── pages/
        │   ├── LoginPage.tsx
        │   ├── RegisterPage.tsx
        │   ├── ChatPage.tsx      # Main chat UI with streaming
        │   └── AdminPage.tsx     # Admin dashboard
        ├── services/
        │   ├── api.ts            # Axios instance + token refresh
        │   └── apiService.ts     # Typed API wrappers
        └── store/
            ├── authStore.ts      # Zustand auth state
            └── chatStore.ts      # Zustand chat + streaming state
```

---

## Quick Start

### 1. Prerequisites
- Docker + Docker Compose
- AWS account (S3 bucket)
- OpenAI API key
- Google Cloud Vision credentials (for OCR)

### 2. Setup

```bash
git clone <repo>
cd rag-app

# Copy and fill in your secrets
cp .env.example .env
nano .env

# Start all services
make up

# Run DB migrations
make migrate

# Create admin user
make seed
```

### 3. Access

| Service     | URL                        |
|-------------|----------------------------|
| Frontend    | http://localhost:3000       |
| API Docs    | http://localhost:8000/docs  |
| Flower      | http://localhost:5555       |
| Qdrant UI   | http://localhost:6333/dashboard |

---

## RBAC Roles

| Permission               | Student | Staff | Admin |
|--------------------------|:-------:|:-----:|:-----:|
| Query documents          | ✓       | ✓     | ✓     |
| Upload documents         |         | ✓     | ✓     |
| Delete documents         |         |       | ✓     |
| View all conversations   |         | ✓     | ✓     |
| Manage users             |         |       | ✓     |
| Block/unblock users      |         |       | ✓     |
| Change roles             |         |       | ✓     |
| View system stats        |         | ✓     | ✓     |

---

## Key Design Decisions

### 1. MMR over Pure Similarity Search
Maximal Marginal Relevance retrieves diverse, non-redundant chunks instead of the top-k most similar. This prevents answers that repeat the same content from slightly different angles.

### 2. Exam Paper Metadata Injection
Each chunk from an exam paper is prefixed with `[Subject: X | Code: Y]`. When the same question appears across multiple years, retrieval is precise because the metadata context differentiates them and allows subject-level filtering.

### 3. Dual-Model Architecture
- **Small model** (gpt-3.5-turbo): intent classification, query rewriting, exam parsing, summarization. Low cost, fast.
- **Large model** (gpt-4o): final answer generation only. Used sparingly for quality.

### 4. Celery for Ingestion
Document processing can take 30–120 seconds (OCR, batch embedding). Running this in Celery ensures the API remains responsive. Clients poll `/documents/{id}/status` for progress.

### 5. Refresh Token Rotation
On each token refresh, the old refresh token is revoked and a new pair is issued. This limits the blast radius of a stolen token.

### 6. Conversation Summarization
Every 20 messages, the conversation is summarized using the small model. This keeps the context window usage bounded for long sessions while preserving conversational continuity.

### 7. Priority Boosting
Exam questions get `priority=1.5`. The MMR relevance score is multiplied by this factor before selection, so question-type chunks surface more reliably for exam-related queries.

---

## Configuration Reference

All settings in `.env` (see `.env.example`):

| Key | Default | Description |
|-----|---------|-------------|
| `SMALL_MODEL` | `gpt-3.5-turbo` | Routing/parsing model |
| `LARGE_MODEL` | `gpt-4o` | Answer generation model |
| `TOP_K_RETRIEVAL` | `8` | Chunks retrieved per query |
| `SIMILARITY_THRESHOLD` | `0.72` | Minimum cosine score to include a chunk |
| `MMR_LAMBDA` | `0.5` | 0=max diversity, 1=max relevance |
| `CHUNK_SIZE` | `512` | Tokens per chunk (normal docs) |
| `CHUNK_OVERLAP` | `64` | Overlap between adjacent chunks |
| `RATE_LIMIT_AUTH` | `60` | Req/min for authenticated users |
| `RATE_LIMIT_ANON` | `10` | Req/min for anonymous sessions |
| `SHORT_TERM_MEMORY_MESSAGES` | `10` | Recent messages sent to LLM |
| `SUMMARY_TRIGGER_MESSAGES` | `20` | Messages before summarization |
| `ANON_SESSION_TTL_HOURS` | `24` | Anonymous session expiry |

---

## Running Tests

```bash
# Inside container
make test

# Locally with pytest
cd backend
pip install -r requirements.txt -r requirements-test.txt
pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## Production Checklist

- [ ] Rotate `SECRET_KEY` to a 64-char random string
- [ ] Set `APP_ENV=production` (disables `/docs`)
- [ ] Use RDS for PostgreSQL (not container volume)
- [ ] Use ElastiCache for Redis
- [ ] Use Qdrant Cloud or dedicated Qdrant cluster
- [ ] Set up CloudFront in front of S3
- [ ] Enable Sentry: set `SENTRY_DSN` in environment
- [ ] Configure log aggregation (CloudWatch, Datadog)
- [ ] Set up Celery worker autoscaling
- [ ] Change default admin password after `make seed`
- [ ] Store `GOOGLE_APPLICATION_CREDENTIALS` as a mounted secret
- [ ] Enable HTTPS (TLS termination at load balancer)
