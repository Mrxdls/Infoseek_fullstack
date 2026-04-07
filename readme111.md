Your production-grade RAG application is complete. Here's what's inside the ZIP:

---

**72 files across the full stack. Here's what every major piece does:**

**Backend (FastAPI + Python)**
- `app/main.py` — App factory with CORS, GZip, rate limiting, Prometheus metrics, lifespan hooks
- `app/core/config.py` — All config via pydantic-settings, loaded from `.env`
- `app/db/models/models.py` — Full ORM schema: Users, Tokens, Documents, Chunks, Conversations, Messages
- `app/services/auth/auth_service.py` — JWT access + refresh tokens, RBAC, bcrypt, token rotation
- `app/services/ingestion/extractor.py` — PyMuPDF for digital PDFs, Google Vision API for scanned, python-docx for DOCX
- `app/services/ingestion/chunker.py` — Three strategies: structure-aware (learning material), per-question with metadata injection (exam papers), tight overlap (OCR)
- `app/services/ingestion/vector_store.py` — Qdrant with MMR retrieval, priority boosting, deduplication
- `app/services/rag/pipeline.py` — Full 7-step pipeline: intent → rewrite → embed → MMR → prompt → generate → guardrails
- `app/services/session/session_service.py` — Short-term memory, rolling summarization every 20 messages, anonymous session expiry
- `app/tasks/celery_app.py` — Full async ingestion task with retry logic, Celery Beat for scheduled cleanup
- `app/api/v1/endpoints/` — Auth, Documents, Chat (with SSE streaming), Admin endpoints

**Frontend (React + TypeScript)**
- Axios with automatic JWT refresh on 401
- Zustand stores for auth and chat state
- Login, Register, Chat (with streaming toggle), Admin dashboard pages
- Source citation cards that expand to show retrieved chunk excerpts
- Role-gated routes (admin panel blocked for students)

**Infrastructure**
- `docker-compose.yml` — API, Celery worker, Celery Beat, Flower, PostgreSQL, Redis, Qdrant, React frontend
- `Makefile` — `make up`, `make migrate`, `make test`, `make seed`, `make logs` etc.
- `scripts/seed_admin.py` — Creates the first admin user
- `alembic/` — Async-compatible migration environment

**To get started:** `cp .env.example .env` → fill in your keys → `make up` → `make migrate` → `make seed`