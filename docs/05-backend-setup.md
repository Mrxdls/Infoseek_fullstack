# 05 — Backend Setup

This guide sets up the Python environment, configures all settings, runs database migrations, and starts the server.

---

## 1. Navigate to Backend Directory

```bash
cd /path/to/rag-app/backend
```

All commands in this guide are run from the `backend/` directory.

---

## 2. Create a Python Virtual Environment

A virtual environment isolates the project's Python packages from your system Python. This prevents version conflicts with other projects.

```bash
python3 -m venv venv
source venv/bin/activate
```

Your terminal prompt should change to show `(venv)`. You must run `source venv/bin/activate` every time you open a new terminal.

To deactivate: `deactivate`

---

## 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This installs ~30 packages. Key ones:

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.111 | Web framework — handles HTTP requests |
| `uvicorn[standard]` | 0.30 | ASGI server — runs FastAPI |
| `sqlalchemy[asyncio]` | 2.0 | Database ORM — Python classes ↔ SQL tables |
| `asyncpg` | 0.29 | Async PostgreSQL driver |
| `alembic` | 1.13 | Database migrations |
| `psycopg2-binary` | 2.9 | Sync PostgreSQL driver (used by Celery) |
| `pgvector` | 0.4 | pgvector SQLAlchemy integration |
| `celery` | 5.4 | Background task queue |
| `redis` | 5.0 | Redis client for Celery + cache |
| `google-genai` | 1.0+ | Gemini SDK |
| `google-cloud-vision` | 3.7 | Vision OCR API |
| `google-cloud-storage` | 2.16 | GCS file storage |
| `pymupdf` | 1.24 | PDF text extraction |
| `python-docx` | 1.1 | DOCX file reading |
| `pydantic` | 2.7 | Request/response validation |
| `bcrypt` | latest | Password hashing |
| `python-jose` | 3.3 | JWT token creation/validation |
| `tenacity` | 8.3 | Retry logic for API calls |
| `structlog` | 24.2 | Structured JSON logging |
| `slowapi` | 0.1 | Rate limiting |

> **If a package fails to install** (common with `psycopg2-binary`): make sure `libpq-dev` is installed (`sudo apt install libpq-dev -y`).

---

## 4. Create the .env File

Copy the example and fill in your values:

```bash
cp .env.example .env    # if .env.example exists, otherwise create from scratch
```

Create `.env` in the `backend/` directory (or project root — the app checks both):

```env
# ── App ────────────────────────────────────────────────────────────────────────
APP_ENV=development
SECRET_KEY=change-this-to-a-long-random-string-64-chars-minimum

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://postgres:root@localhost:5432/infoseek
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=infoseek
POSTGRES_USER=postgres
POSTGRES_PASSWORD=root

# ── Redis ──────────────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
CACHE_TTL_SECONDS=3600

# ── GCP ────────────────────────────────────────────────────────────────────────
GCP_PROJECT_ID=your-gcp-project-id
GCP_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/your-service-account-key.json

# ── GCS ────────────────────────────────────────────────────────────────────────
GCS_BUCKET_NAME=your-bucket-name

# ── Gemini Models ──────────────────────────────────────────────────────────────
GEMINI_LARGE_MODEL=gemini-2.5-pro
GEMINI_SMALL_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIMS=3072
MAX_TOKENS_RESPONSE=2048

# ── CORS (add your frontend origin) ───────────────────────────────────────────
CORS_ORIGINS=["http://localhost:3000"]

# ── JWT ────────────────────────────────────────────────────────────────────────
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
ALGORITHM=HS256

# ── Rate Limiting ──────────────────────────────────────────────────────────────
RATE_LIMIT_AUTH=60
RATE_LIMIT_ANON=10

# ── RAG Settings ───────────────────────────────────────────────────────────────
TOP_K_RETRIEVAL=8
SIMILARITY_THRESHOLD=0.65
CHUNK_SIZE=512
CHUNK_OVERLAP=64
EMBED_BATCH_SIZE=50

# ── Session / Memory ───────────────────────────────────────────────────────────
ANON_SESSION_TTL_HOURS=24
SHORT_TERM_MEMORY_MESSAGES=10
SUMMARY_TRIGGER_MESSAGES=20
```

### Generating a SECRET_KEY

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# Prints something like: a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1
```

Copy that output and use it as your `SECRET_KEY`.

> **Never share or commit your `.env` file.** It contains your GCP credentials path and JWT secret.

---

## 5. Run Database Migrations

Alembic manages the database schema. Migrations are SQL scripts that create/modify tables, versioned in `alembic/versions/`.

```bash
# Apply all pending migrations
alembic upgrade head
```

The first run creates these tables:
- `users`
- `refresh_tokens`
- `documents`
- `document_chunks` (with `vector(3072)` column)
- `notes` (with `vector(3072)` column)
- `conversations`
- `messages`

The second migration adds:
- `syllabus` table
- `pg_trgm` extension
- GIN index on `syllabus.subject_name` for fuzzy search

You should see output like:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 001, GCP pgvector migration
INFO  [alembic.runtime.migration] Running upgrade 001 -> 002, Add syllabus table
```

> **If migration fails:** See [14 — Troubleshooting](./14-troubleshooting.md) for common errors.

---

## 6. Create the Admin User

Run the seed script to create the first admin account:

```bash
python scripts/seed_admin.py
```

This creates:
- Email: `admin@studyrag.com`
- Password: `admin123`
- Role: `admin`

**Change the password after first login** (via the admin panel or by updating the DB directly).

---

## 7. Start the Development Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`--reload` watches for file changes and restarts automatically. Remove it in production.

You should see:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

The API docs are at [http://localhost:8000/docs](http://localhost:8000/docs) — an interactive Swagger UI listing every endpoint.

---

## 8. Start the Celery Worker

Open a **second terminal**, activate the venv, and run:

```bash
cd /path/to/rag-app/backend
source venv/bin/activate
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
```

- `-A app.tasks.celery_app` — points to the Celery app instance
- `--loglevel=info` — shows task progress in the terminal
- `--concurrency=2` — runs 2 parallel workers (reduce to 1 if memory constrained)

You should see:
```
celery@hostname ready.
[tasks]
  . app.tasks.celery_app.expire_stale_sessions
  . app.tasks.celery_app.process_document
```

**Both the web server and Celery worker must be running** for document uploads to be processed.

---

## 9. Verify the Setup

```bash
# Health check
curl http://localhost:8000/api/v1/health
# Expected: {"status": "ok", "version": "1.0.0"}

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@studyrag.com","password":"admin123"}'
# Expected: {"access_token":"eyJ...", "refresh_token":"eyJ..."}
```

---

## Directory Layout of the Backend

```
backend/
├── alembic/
│   ├── env.py              # Alembic configuration (connects to DB)
│   └── versions/
│       ├── 001_gcp_pgvector_migration.py  # Creates all base tables
│       └── 002_syllabus.py                # Adds syllabus table + pg_trgm
├── app/
│   ├── main.py             # FastAPI app factory + startup/shutdown
│   ├── api/v1/
│   │   ├── router.py       # Aggregates all endpoint routers
│   │   └── endpoints/
│   │       ├── auth.py
│   │       ├── chat.py
│   │       ├── documents.py
│   │       └── admin.py
│   ├── core/
│   │   ├── config.py       # Settings (Pydantic BaseSettings)
│   │   ├── exceptions.py   # Global HTTP exception handlers
│   │   ├── logging.py      # structlog configuration
│   │   └── rate_limiter.py # SlowAPI instance
│   ├── db/
│   │   ├── models/models.py  # All SQLAlchemy ORM models
│   │   └── session.py        # Async engine, session factory, Base
│   ├── schemas/schemas.py    # Pydantic request/response models
│   ├── services/             # Business logic
│   ├── tasks/celery_app.py   # Background tasks
│   └── utils/cache.py        # Redis cache utilities
├── scripts/seed_admin.py
├── requirements.txt
└── alembic.ini
```
