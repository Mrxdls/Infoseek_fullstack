# 14 — Troubleshooting

This guide covers every significant error encountered during development and exactly how to fix each one.

---

## Database / Migration Errors

### "userrole already exists" (or similar enum already exists)

**Full error:**
```
sqlalchemy.exc.ProgrammingError: (psycopg2.errors.DuplicateObject) type "userrole" already exists
```

**Cause:** A previous migration run partially succeeded, leaving some enums created but others missing. Alembic doesn't know the migration ran.

**Fix:**
```bash
# Connect to database
sudo -u postgres psql -d infoseek

# Drop all enum types the migration created
DROP TYPE IF EXISTS userrole CASCADE;
DROP TYPE IF EXISTS documenttype CASCADE;
DROP TYPE IF EXISTS documentstatus CASCADE;
DROP TYPE IF EXISTS sessiontype CASCADE;
DROP TYPE IF EXISTS messagerole CASCADE;

-- Also drop all tables if they exist
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS conversations CASCADE;
DROP TABLE IF EXISTS notes CASCADE;
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS syllabus CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS refresh_tokens CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- Clear migration history
DELETE FROM alembic_version;
\q
```

Then re-run migrations:
```bash
alembic upgrade head
```

---

### "cannot insert multiple commands into a prepared statement"

**Full error:**
```
asyncpg.exceptions.InterfaceError: cannot insert multiple commands into a prepared statement
```

**Cause:** asyncpg (the async PostgreSQL driver) does not support running multiple SQL statements in a single `op.execute()` call. You must separate each statement.

**Fix:** Split any `op.execute()` that contains multiple SQL statements:
```python
# WRONG — multiple statements in one call
op.execute("""
    CREATE TABLE a (...);
    CREATE TABLE b (...);
""")

# CORRECT — one statement per call
op.execute("CREATE TABLE a (...)")
op.execute("CREATE TABLE b (...)")
```

---

### "column cannot have more than 2000 dimensions for hnsw/ivfflat index"

**Full error:**
```
psycopg2.errors.InternalError_: column cannot have more than 2000 dimensions for hnsw/ivfflat index
```

**Cause:** pgvector version 0.6.0 (the version available in PostgreSQL apt repositories) limits ANN indexes (HNSW and IVFFlat) to 2000 dimensions. The project uses 3072-dimensional embeddings.

**Fix:** Remove the index creation from your migration. The system falls back to sequential scan (`ORDER BY embedding <=> :vec`) which is acceptable for development with < 100,000 rows.

If you need ANN indexes in production, upgrade to pgvector 0.7.0+ (available in Cloud SQL on GCP) which removes the dimension limit.

---

### "invalid input value for enum userrole: ADMIN"

**Full error:**
```
sqlalchemy.exc.DataError: (psycopg2.errors.InvalidTextRepresentation) invalid input value for enum userrole: "ADMIN"
```

**Cause:** PostgreSQL stores enum values as their text representation. By default, SQLAlchemy uses the Python enum member name (`ADMIN`, `STAFF`) not the value (`admin`, `staff`).

**Fix:** All enums must use `values_callable` to store lowercase values:
```python
def _pg_enum(enum_cls, **kw):
    return Enum(enum_cls, values_callable=lambda x: [e.value for e in x], **kw)
```

This is already applied in `models.py`. If you add a new enum column, use `_pg_enum()`.

---

## Authentication Errors

### "Invalid credentials" when password is correct

**Cause:** The password was hashed using raw bcrypt (without SHA-256 prehashing), but the auth service expects SHA-256 prehashing.

**Diagnosis:**
```python
import bcrypt, hashlib, base64

# The auth service prehashes like this:
def _prehash(password):
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")

# Check if stored hash verifies with prehash
password = "admin123"
stored_hash = "the hash from the database"
result = bcrypt.checkpw(_prehash(password).encode("ascii"), stored_hash.encode("ascii"))
print("Verifies:", result)
```

**Fix:** Re-hash the password using the correct method:
```bash
cd backend && source venv/bin/activate
python3 -c "
from app.services.auth.auth_service import hash_password
from sqlalchemy import create_engine, text
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL.replace('+asyncpg',''))
new_hash = hash_password('admin123')
with engine.begin() as conn:
    conn.execute(text(
        \"UPDATE users SET hashed_password=:h WHERE email='admin@studyrag.com'\"
    ), {'h': new_hash})
print('Done')
"
```

---

## Celery / Background Processing Errors

### Celery worker is not processing tasks

**Symptoms:** Documents stay in `pending` status indefinitely.

**Diagnosis:**
```bash
# Check if worker is running
ps aux | grep celery | grep -v grep

# Check Redis for queued tasks
redis-cli -n 1 llen celery
```

**Fix:** Start the worker:
```bash
cd backend && source venv/bin/activate
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
```

If the worker crashed with an unhandled exception, check:
```bash
tail -100 /tmp/celery.log
```

---

### Document processing fails with `KeyError`

**Symptom:** Error message contains something like `KeyError: '\n  "metadata"'`

**Cause:** A prompt template that uses `.format()` has literal `{` `}` braces in the body (e.g., in JSON examples in the prompt). Python tries to interpret them as format placeholders.

**Fix:** Use `.replace('{placeholder}', value)` instead of `.format(placeholder=value)`:
```python
# WRONG
prompt = MY_PROMPT.format(text=content)

# CORRECT (when prompt contains literal { })
prompt = MY_PROMPT.replace("{text}", content)
```

---

### "JSON parse failed" — model returns truncated JSON

**Symptom:** Logs show `generate_json failed after retries error=Unterminated string...`

**Cause:** The `max_tokens` limit is too low. The model started generating a long JSON response but was cut off mid-string.

**Fix:** Increase `max_tokens` in the Gemini call:
```python
raw = self._gemini.generate_json(
    prompt=prompt,
    model=self._gemini._small,
    max_tokens=8192,   # was 4096
)
```

For syllabus subjects with many units (10+), 4096 tokens is not enough.

---

## GCP / Vertex AI Errors

### "API has not been enabled"

**Fix:** Go to GCP Console → APIs & Services → Library → Search for the API → Enable.

APIs needed:
- Vertex AI API (`aiplatform.googleapis.com`)
- Cloud Storage API (`storage.googleapis.com`)
- Cloud Vision API (`vision.googleapis.com`)

---

### "Permission denied" on GCS

**Cause:** The service account doesn't have the right IAM role.

**Fix:** Go to IAM & Admin → IAM → find your service account → add "Storage Object Admin" role.

---

### "Location X is not supported for this model"

**Fix:** Change `GCP_LOCATION` to `us-central1`. This region supports all Gemini models.

---

## Frontend Errors

### "Objects are not valid as a React child"

**Cause:** Pydantic v2 validation errors return `detail` as an array of objects, not a string. Rendering an object directly as JSX text throws this error.

**Fix:** Check if detail is an array before displaying:
```typescript
const detail = err?.response?.data?.detail;
if (Array.isArray(detail)) {
    setError(detail.map((e: any) => e.msg || JSON.stringify(e)).join('; '));
} else if (typeof detail === 'string') {
    setError(detail);
} else {
    setError('An error occurred');
}
```

This fix is already in the codebase (`ChatPage.tsx`).

---

### Messages disappearing from conversation history

**Cause:** `SessionService.add_message()` only called `flush()` (writes to the DB session in memory) but not `commit()` (persists to disk). If the request handler failed after saving the user message but before saving the assistant message, the flush was rolled back.

**Fix:** Always commit immediately after saving a message:
```python
async def add_message(self, ...):
    msg = Message(...)
    self.db.add(msg)
    await self.db.flush()
    await self.db.commit()   # ← commit immediately, never lose messages
    return msg
```

This fix is already applied in the codebase.

---

### CORS error in browser

**Symptom:** Browser console shows `Access-Control-Allow-Origin` error.

**Fix:** Add your frontend's origin to `CORS_ORIGINS` in `.env`:
```env
CORS_ORIGINS=["http://localhost:3000", "http://localhost:3001"]
```

The value must be a JSON array (with square brackets and quotes).

---

## Performance Issues

### Slow vector search (sequential scan)

**Symptom:** Search queries take 2–10 seconds on large datasets.

**Cause:** pgvector 0.6.0 cannot create ANN indexes (HNSW/IVFFlat) for vectors > 2000 dimensions. The system uses sequential scan instead.

**Options:**
1. **Upgrade to pgvector 0.7.0+** — removes the dimension limit. Available on Cloud SQL.
2. **Reduce embedding dimensions** — change `EMBEDDING_DIMS=768` in `.env`, then re-embed all documents. This enables indexes but reduces accuracy.
3. **Accept the limitation** — for datasets under ~100,000 chunks, sequential scan with `ORDER BY embedding <=> :vec` typically completes in under 100ms.

---

### High Gemini API costs

**Reduce costs by:**
1. Decreasing `MAX_TOKENS_RESPONSE` from 2048 to 1024
2. Using `gemini-2.5-flash` for the final answer (change `self._gemini._large` to `self._gemini._small` in the pipeline)
3. Increasing `CACHE_TTL_SECONDS` to cache responses longer
4. Reducing `SHORT_TERM_MEMORY_MESSAGES` from 10 to 4

---

## Checking System Health

Quick diagnostic commands:

```bash
# Backend health
curl http://localhost:8000/api/v1/health

# Database connection
cd backend && source venv/bin/activate
python3 -c "
from sqlalchemy import create_engine, text
from app.core.config import settings
engine = create_engine(settings.DATABASE_URL.replace('+asyncpg',''))
with engine.connect() as conn:
    result = conn.execute(text('SELECT COUNT(*) FROM users'))
    print('Users:', result.fetchone()[0])
    result = conn.execute(text('SELECT COUNT(*) FROM notes'))
    print('Note chunks:', result.fetchone()[0])
    result = conn.execute(text('SELECT COUNT(*) FROM document_chunks'))
    print('Exam chunks:', result.fetchone()[0])
    result = conn.execute(text('SELECT COUNT(*) FROM syllabus'))
    print('Syllabus subjects:', result.fetchone()[0])
"

# Redis connection
redis-cli ping

# Celery worker tasks
redis-cli -n 1 llen celery
```
