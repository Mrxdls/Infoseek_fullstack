# 07 — System Architecture

This document explains how all parts of the system connect to each other, and traces the full path of two key operations: uploading a document and asking a question.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          User's Browser                             │
│                    React SPA (port 3000)                            │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTP/HTTPS
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend (port 8000)                    │
│                                                                     │
│  /api/v1/auth/*      /api/v1/documents/*    /api/v1/chat/*          │
│  Auth endpoints      Upload, status, list   Query (RAG), stream     │
│                                                                     │
│  RAGPipeline         SessionService         AuthService             │
│  VectorStoreService  GeminiClient           GCSService              │
└────┬──────────────────────┬──────────────────────┬──────────────────┘
     │                      │                      │
     ▼                      ▼                      ▼
┌─────────┐          ┌────────────┐         ┌──────────┐
│PostgreSQL│          │   Redis    │         │   GCS    │
│+ pgvector│          │(broker/    │         │(PDF files│
│          │          │ cache)     │         │          │
└─────────┘          └──────┬─────┘         └──────────┘
                            │ task queue
                            ▼
                   ┌─────────────────┐
                   │  Celery Worker  │
                   │  (background)   │
                   │                 │
                   │ process_document│
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │  Google Vertex AI│
                   │  - Gemini Pro    │
                   │  - Gemini Flash  │
                   │  - Embeddings    │
                   └─────────────────┘
```

---

## Data Flow 1: Document Upload

Here is exactly what happens when an admin uploads a PDF:

```
Browser                FastAPI               Redis              Celery Worker
  │                       │                    │                     │
  │── POST /documents/upload ──►               │                     │
  │   (multipart/form-data)                    │                     │
  │                       │                    │                     │
  │                       ├── upload bytes ──► GCS bucket            │
  │                       │                    │                     │
  │                       ├── INSERT Document row (status=pending)   │
  │                       │                    │                     │
  │                       ├── push task ──────►│                     │
  │                       │   process_document │                     │
  │◄── 201 { document_id, task_id } ──────────│                     │
  │                       │                    │                     │
  │                       │                    │── dequeue task ────►│
  │                       │                    │                     │
  │                       │                    │               download from GCS
  │                       │                    │                     │
  │                       │                    │          extract text (PyMuPDF)
  │                       │                    │          [OCR via Vision if sparse]
  │                       │                    │                     │
  │                       │                    │       [if notes]    │
  │                       │                    │       detect subject via Gemini Flash
  │                       │                    │       chunk per page
  │                       │                    │                     │
  │                       │                    │       [if exam]     │
  │                       │                    │       extract questions via Gemini Pro
  │                       │                    │       one chunk per question
  │                       │                    │                     │
  │                       │                    │       [if syllabus] │
  │                       │                    │       group pages by subject code regex
  │                       │                    │       extract structured data via Gemini Flash
  │                       │                    │                     │
  │                       │                    │       embed all chunks (Gemini embedding-001)
  │                       │                    │       INSERT into notes/document_chunks/syllabus
  │                       │                    │                     │
  │                       │                    │       UPDATE Document status=indexed
  │                       │                    │                     │
  │── GET /documents/{id}/status ─────────────────────────────────► │
  │◄── { status: "indexed", chunk_count: 334 } ─────────────────────│
```

**Key points:**
- The HTTP response from `/upload` returns immediately (within ~1 second) with a `task_id`
- All heavy processing (60–120 seconds) happens in the Celery worker
- The browser can poll `/documents/{id}/status` to check progress

---

## Data Flow 2: Chat Query

Here is what happens when a student asks a question:

```
Browser              FastAPI              PostgreSQL          Vertex AI
  │                     │                     │                   │
  │── POST /chat/query ►│                     │                   │
  │   { conversation_id,│                     │                   │
  │     message }       │                     │                   │
  │                     │                     │                   │
  │                 load recent msgs ─────────►                   │
  │                     │◄────── last 10 messages ────────────────│
  │                     │                     │                   │
  │                 check response cache (Redis)                  │
  │                     │                     │                   │
  │                 save user message ────────►                   │
  │                     │                     │                   │
  │               ── RAG Pipeline ──           │                   │
  │                     │                     │                   │
  │                classify_intent ────────────────────── Gemini Flash
  │                     │◄─── {intent: "cross_reference",         │
  │                     │      subject_hint: "Machine Learning",   │
  │                     │      unit_hint: 3}                      │
  │                     │                     │                   │
  │                syllabus_topic_lookup ──────►                  │
  │                     │◄─── Unit 3 topics: clustering, k-means  │
  │                     │                     │                   │
  │                embed enriched query ────────────────── Gemini Embeddings
  │                     │◄─── [0.12, -0.34, 0.56, ...]            │
  │                     │                     │                   │
  │                vector search exam_chunks ─►                   │
  │                     │◄─── top-8 relevant questions            │
  │                     │                     │                   │
  │                vector search notes ────────►                  │
  │                     │◄─── top-8 relevant note pages           │
  │                     │                     │                   │
  │                merge + MMR deduplicate     │                   │
  │                     │                     │                   │
  │                build messages (context block)                 │
  │                     │                     │                   │
  │                agenerate_with_history ─────────────── Gemini Pro
  │                     │◄─── "Unit 3 covers unsupervised..."     │
  │                     │                     │                   │
  │                save assistant message ─────►                  │
  │                     │                     │                   │
  │◄── 200 { answer, sources, intent, latency } ─────────────────│
```

---

## The 6-Intent Router

The heart of the RAG pipeline is intent classification. Before searching anything, Gemini Flash reads the user's question and recent conversation history and returns one of six intents:

| Intent | Meaning | What Gets Retrieved |
|--------|---------|-------------------|
| `exam_question` | "What questions came from TCP in the exam?" | `document_chunks` only |
| `concept_explain` | "Explain what TCP/IP is" | `notes` only |
| `exam_prep` | "Help me prepare chapter 3 TCP" | `document_chunks` + `notes` |
| `syllabus_unit` | "What topics are in unit 3 of Machine Learning?" | Syllabus lookup → `notes` |
| `cross_reference` | "Unit 3 ML questions with answers" | Syllabus → `document_chunks` + `notes` |
| `chit_chat` | "Hi, how are you?" | No retrieval — Gemini answers directly |

The intent also extracts:
- `subject_hint` — subject name mentioned in the query (e.g., "Machine Learning")
- `unit_hint` — unit/chapter number (e.g., 3)

For `syllabus_unit` and `cross_reference`, the pipeline looks up the syllabus table using fuzzy matching (`pg_trgm`) to find the subject, then extracts the topics from that unit, and uses those topics to enrich the search query before embedding.

---

## Memory Architecture

The system maintains three layers of memory for each conversation:

```
Layer 1 — Current Context
  The 10 most recent messages passed directly to Gemini with every request.
  Stored in: PostgreSQL messages table
  Controlled by: SHORT_TERM_MEMORY_MESSAGES=10

Layer 2 — Rolling Summary
  After every 20 messages, Gemini Flash summarizes the conversation so far.
  The summary is stored on the Conversation row and prepended to future requests.
  Controlled by: SUMMARY_TRIGGER_MESSAGES=20

Layer 3 — Retrieved Context
  Document chunks retrieved from pgvector for the current query.
  TOP_K_RETRIEVAL=8 chunks selected.
```

This means: even a 500-message conversation stays within Gemini's context window, because older messages are compressed into a summary.

---

## Authentication Flow

```
Client                  FastAPI
  │                        │
  │── POST /auth/login ────►│
  │                        ├── verify password (bcrypt)
  │                        ├── create access_token (JWT, 60 min)
  │                        ├── create refresh_token (JWT, 7 days)
  │                        ├── store refresh_token hash in DB
  │◄── {access_token, refresh_token} ─────────────────────────────
  │                        │
  │  [Every protected request]
  │── GET /chat/conversations
  │   Authorization: Bearer {access_token}
  │                        ├── decode JWT, verify signature
  │                        ├── look up user by sub (user_id)
  │                        ├── check user.is_active
  │◄── 200 OK ─────────────│
  │                        │
  │  [When access token expires]
  │── POST /auth/refresh ───►│
  │   {refresh_token}       ├── verify refresh_token hash in DB
  │                        ├── revoke old refresh_token
  │                        ├── issue new token pair
  │◄── {new_access_token, new_refresh_token} ─────────────────────
```

**Password security:** Passwords are SHA-256 hashed first (to handle passwords > 72 bytes), then bcrypt hashed with a random salt. The bcrypt hash is stored in the database.

**JWT security:** Tokens are signed with `SECRET_KEY` using HS256. The payload contains `{sub: user_id, exp: timestamp, type: "access"|"refresh", jti: uuid}`. The `jti` (JWT ID) prevents token reuse.

---

## Component Responsibilities Summary

| Component | File | Responsibility |
|-----------|------|----------------|
| `GCSService` | `services/ingestion/gcs_service.py` | Upload/download/delete files from GCS |
| `DocumentExtractor` | `services/ingestion/extractor.py` | Convert PDF/DOCX/TXT bytes → text (+ OCR fallback) |
| `ExamProcessor` | `services/ingestion/exam_processor.py` | Ask Gemini Pro to extract structured questions from exam text |
| `NotesProcessor` | `services/ingestion/notes_processor.py` | Per-page chunking + Gemini Flash subject detection |
| `SyllabusProcessor` | `services/ingestion/syllabus_processor.py` | Page grouping by subject, structured extraction per subject |
| `VectorStoreService` | `services/ingestion/vector_store.py` | pgvector upsert/search/delete |
| `GeminiClient` | `services/llm/gemini_client.py` | All calls to Gemini (generate, embed, stream, json) |
| `RAGPipeline` | `services/rag/pipeline.py` | Orchestrates intent → retrieval → generation |
| `SessionService` | `services/session/session_service.py` | Conversations, messages, summaries |
| `AuthService` | `services/auth/auth_service.py` | Register, login, JWT, refresh token rotation |
| `CacheService` | `utils/cache.py` | Redis get/set for response caching |
| `process_document` | `tasks/celery_app.py` | Background task: full ingestion pipeline |
