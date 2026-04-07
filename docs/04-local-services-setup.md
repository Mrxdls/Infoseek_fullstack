# 04 — Local Services Setup

This guide sets up PostgreSQL with the pgvector extension and Redis. Both run locally on your machine during development.

---

## PostgreSQL Setup

### 1. Create the Database

```bash
# Switch to the postgres system user
sudo -u postgres psql

# Inside psql:
CREATE DATABASE infoseek;
CREATE USER postgres WITH PASSWORD 'root';
GRANT ALL PRIVILEGES ON DATABASE infoseek TO postgres;
\q
```

> **The project uses database name `infoseek`, user `postgres`, password `root` by default.** You can change these in `.env` later.

### 2. Install pgvector Extension

pgvector is a PostgreSQL extension that adds support for vector columns and similarity search. It must be installed at the operating system level before it can be enabled in the database.

```bash
# Ubuntu — build from source (most reliable method)
sudo apt install build-essential postgresql-server-dev-15 -y

git clone --branch v0.6.0 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
cd ..
rm -rf pgvector
```

> **Note:** Replace `postgresql-server-dev-15` with your PostgreSQL version number (e.g., `postgresql-server-dev-16`).

Verify installation:
```bash
sudo -u postgres psql -d infoseek -c "CREATE EXTENSION IF NOT EXISTS vector;"
# Should print: CREATE EXTENSION
```

> **Why pgvector?** PostgreSQL already stores all our structured data (users, conversations, documents). Adding pgvector means we can store and search vector embeddings in the same database without a second vector database. The `<=>` operator performs cosine distance search.

> **Learn more:** [pgvector GitHub](https://github.com/pgvector/pgvector)

### 3. Install pg_trgm Extension (for fuzzy subject name matching)

pg_trgm is a standard PostgreSQL extension (no extra installation needed) that supports trigram-based similarity search. The syllabus search uses it to match subject names even with typos.

```bash
sudo -u postgres psql -d infoseek -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
# Should print: CREATE EXTENSION
```

> **What trigrams are:** "hello" → {hel, ell, llo}. Two strings are similar if they share many trigrams. `similarity('Machine Learning', 'machine learn') = 0.72`. Used to match user queries like "ML" to "Machine Learning" in the syllabus.

### 4. Verify PostgreSQL Connection

```bash
psql -U postgres -d infoseek -h localhost -c "SELECT version();"
# Enter password: root
```

If it shows the PostgreSQL version, the database is set up correctly.

---

## Redis Setup

Redis is used for two things:
1. **Celery broker** — tasks queued for background processing live in Redis
2. **Response cache** — identical queries within 1 hour return the cached answer

### 1. Verify Redis Is Running

```bash
redis-cli ping
# Should print: PONG
```

### 2. Check Redis Is Accessible on Default Port

```bash
redis-cli -p 6379 info server | grep redis_version
# redis_version:7.x.x
```

### 3. Redis Database Allocation

The project uses three Redis database numbers:
- `db 0` — general cache (API response cache)
- `db 1` — Celery task broker (task queue)
- `db 2` — Celery result backend (task results)

These are separate namespaces in the same Redis instance. No extra configuration needed — Redis supports 16 databases (0–15) by default.

---

## Optional: PostgreSQL Configuration for Performance

For development, default PostgreSQL settings work fine. For better performance with larger datasets, edit `/etc/postgresql/15/main/postgresql.conf`:

```
shared_buffers = 256MB          # increase from default 128MB
work_mem = 16MB                 # per-query memory for sorts/joins
maintenance_work_mem = 256MB    # for vacuum, index creation
```

Then restart:
```bash
sudo systemctl restart postgresql
```

---

## Connection URLs Format

The project uses these URL formats in `.env`:

```
# PostgreSQL (async driver for FastAPI)
DATABASE_URL=postgresql+asyncpg://postgres:root@localhost:5432/infoseek

# Redis (general cache)
REDIS_URL=redis://localhost:6379/0

# Redis (Celery broker)
CELERY_BROKER_URL=redis://localhost:6379/1

# Redis (Celery results)
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

The `+asyncpg` part tells SQLAlchemy to use the async PostgreSQL driver. When the Celery worker connects (which is synchronous), the URL is modified at runtime to remove the `+asyncpg`.

---

## Summary Checklist

- [ ] PostgreSQL running (`sudo systemctl status postgresql`)
- [ ] Database `infoseek` created
- [ ] User `postgres` with password `root` (or your chosen credentials)
- [ ] pgvector extension installed and enabled in `infoseek`
- [ ] pg_trgm extension enabled in `infoseek`
- [ ] Redis running (`redis-cli ping` → `PONG`)
