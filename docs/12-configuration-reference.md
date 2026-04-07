# 12 — Configuration Reference

All configuration is loaded from a `.env` file by `backend/app/core/config.py` using Pydantic Settings. The file is looked for in: `project_root/.env` → `backend/.env` → current directory `.env`.

---

## Application

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | Environment name. Set to `production` to disable Swagger UI (`/docs` and `/redoc`) |
| `SECRET_KEY` | (required) | Random secret for signing JWT tokens. Must be at least 32 characters. Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ALGORITHM` | `HS256` | JWT signing algorithm. HS256 is HMAC-SHA256. Don't change this. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | How long access tokens are valid. After expiry, clients use the refresh token. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | How long refresh tokens are valid. After this, users must log in again. |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | List of allowed frontend origins for CORS. In production, add your domain: `["https://yourdomain.com"]` |

---

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:root@localhost:5432/infoseek` | Full connection URL for the async driver (asyncpg). The `+asyncpg` part is required by SQLAlchemy's async engine. |
| `POSTGRES_HOST` | `localhost` | Database host (used separately for Celery's sync connection) |
| `POSTGRES_PORT` | `5432` | Standard PostgreSQL port |
| `POSTGRES_DB` | `infoseek` | Database name |
| `POSTGRES_USER` | `postgres` | Database username |
| `POSTGRES_PASSWORD` | `root` | Database password |

**Note:** Celery workers use a synchronous connection URL derived from `DATABASE_URL` by stripping `+asyncpg`. This happens automatically in `tasks/celery_app.py`:
```python
_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
```

---

## Redis & Celery

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for response caching (DB 0) |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery task queue (DB 1). Workers poll this for new tasks. |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Where Celery stores task results (DB 2) |
| `CACHE_TTL_SECONDS` | `3600` | How long identical queries are cached (1 hour). Set to 0 to disable caching. |

---

## Google Cloud Platform

| Variable | Default | Description |
|----------|---------|-------------|
| `GCP_PROJECT_ID` | (required) | Your GCP project ID, e.g., `studyrag-dev-123456`. Find it in the GCP console top bar. |
| `GCP_LOCATION` | `us-central1` | Region for Vertex AI models. Must be a region where Gemini models are available. `us-central1` works for all models. |
| `GOOGLE_APPLICATION_CREDENTIALS` | (required) | Absolute path to the service account JSON key file, e.g., `/home/user/keys/studyrag-key.json`. This file authenticates all GCP calls. |

---

## Google Cloud Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `GCS_BUCKET_NAME` | (required) | Name of the GCS bucket for storing uploaded PDFs, e.g., `studyrag-documents`. Must be globally unique. |

Uploaded files are stored with the key pattern: `documents/{user_id}/{uuid}{ext}`

---

## Gemini Models

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_LARGE_MODEL` | `gemini-2.5-pro` | Large model for: exam extraction (detailed structured output), final answer generation. More accurate, slower, costs more. |
| `GEMINI_SMALL_MODEL` | `gemini-2.5-flash` | Fast model for: intent classification, query rewriting, subject detection, syllabus extraction, conversation summaries. |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model. Produces 3072-dimensional vectors. Do not change without also changing `EMBEDDING_DIMS` and re-creating all embeddings. |
| `EMBEDDING_DIMS` | `3072` | Output dimensions of the embedding model. Can be reduced (e.g., to 768) for faster search at the cost of accuracy. Requires re-embedding everything. |
| `MAX_TOKENS_RESPONSE` | `2048` | Maximum tokens in the final generated answer. Increase if answers are being cut off, decrease to save cost. |

---

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_AUTH` | `60` | Requests per minute for authenticated users |
| `RATE_LIMIT_ANON` | `10` | Requests per minute for anonymous/public endpoints (`/auth/login`, `/auth/register`) |

---

## RAG Parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `CHUNK_SIZE` | `512` | Target chunk size in approximate tokens (1 token ≈ 4 chars) for text splitting. Only used by `NotesChunker` (page-level chunking ignores this). |
| `CHUNK_OVERLAP` | `64` | Number of tokens to overlap between consecutive chunks. Ensures context isn't lost at chunk boundaries. |
| `TOP_K_RETRIEVAL` | `8` | Maximum number of chunks to retrieve per search. The final context uses up to 8 exam + 8 notes = 16 chunks (then merged to TOP_K=8 total). |
| `SIMILARITY_THRESHOLD` | `0.65` | Minimum cosine similarity for a chunk to be included in results (0 to 1). Chunks below this threshold are discarded even if they're the closest match. Raise to get fewer, higher-quality results; lower to get more results. |
| `MMR_LAMBDA` | `0.5` | Stored for future MMR use (balance between relevance and diversity, 0=max diversity, 1=max relevance). |
| `EMBED_BATCH_SIZE` | `50` | Maximum texts per Gemini embedding API call. Gemini's limit is 100; we use 50 to be conservative. |

---

## Session & Memory

| Variable | Default | Description |
|----------|---------|-------------|
| `ANON_SESSION_TTL_HOURS` | `24` | How long anonymous (non-logged-in) sessions last before expiring. |
| `SHORT_TERM_MEMORY_MESSAGES` | `10` | Number of recent messages to include in every request to Gemini. Gives the model short-term conversation memory. Increasing this uses more tokens per request (costs more). |
| `SUMMARY_TRIGGER_MESSAGES` | `20` | When total message count in a conversation reaches a multiple of this, Gemini Flash summarizes the conversation. This summary replaces the oldest messages to keep context within limits. |

---

## Complete Example .env File

```env
APP_ENV=development
SECRET_KEY=a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1

DATABASE_URL=postgresql+asyncpg://postgres:root@localhost:5432/infoseek
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=infoseek
POSTGRES_USER=postgres
POSTGRES_PASSWORD=root

REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
CACHE_TTL_SECONDS=3600

GCP_PROJECT_ID=studyrag-dev-123456
GCP_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/home/yourname/keys/studyrag-key.json

GCS_BUCKET_NAME=studyrag-documents-yourname

GEMINI_LARGE_MODEL=gemini-2.5-pro
GEMINI_SMALL_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIMS=3072
MAX_TOKENS_RESPONSE=2048

CORS_ORIGINS=["http://localhost:3000"]
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

RATE_LIMIT_AUTH=60
RATE_LIMIT_ANON=10

TOP_K_RETRIEVAL=8
SIMILARITY_THRESHOLD=0.65
CHUNK_SIZE=512
CHUNK_OVERLAP=64
EMBED_BATCH_SIZE=50

ANON_SESSION_TTL_HOURS=24
SHORT_TERM_MEMORY_MESSAGES=10
SUMMARY_TRIGGER_MESSAGES=20
```
