# StudyRAG — Documentation Index

**StudyRAG** is an AI-powered study assistant that lets university students ask questions about their uploaded lecture notes, exam papers, and syllabi. It uses Retrieval-Augmented Generation (RAG) to give answers grounded only in the uploaded materials, not general internet knowledge.

---

## Documentation Map

| File | What It Covers |
|------|---------------|
| [01 — Project Overview](./01-project-overview.md) | What the system does, key concepts explained in plain English |
| [02 — Prerequisites & Accounts](./02-prerequisites-and-accounts.md) | Software to install, accounts to create before you begin |
| [03 — GCP Setup](./03-gcp-setup.md) | Google Cloud project, Vertex AI, GCS bucket, service account key |
| [04 — Local Services Setup](./04-local-services-setup.md) | PostgreSQL + pgvector, Redis installation and configuration |
| [05 — Backend Setup](./05-backend-setup.md) | Python environment, dependencies, .env file, database migrations, running the server |
| [06 — Frontend Setup](./06-frontend-setup.md) | Node.js, npm install, running the React app |
| [07 — System Architecture](./07-system-architecture.md) | Full architecture diagram, data flow, how all pieces connect |
| [08 — Database Schema](./08-database-schema.md) | Every table, every column, relationships explained |
| [09 — Document Ingestion Pipeline](./09-document-ingestion-pipeline.md) | How PDFs are processed: extract → chunk → embed → store |
| [10 — RAG Pipeline](./10-rag-pipeline.md) | How queries become answers: intent → retrieval → generation |
| [11 — API Reference](./11-api-reference.md) | Every HTTP endpoint, request/response shapes, examples |
| [12 — Configuration Reference](./12-configuration-reference.md) | Every setting in `.env` explained |
| [13 — Running in Production](./13-production-deployment.md) | Systemd services, reverse proxy, environment hardening |
| [14 — Troubleshooting](./14-troubleshooting.md) | Common errors and exactly how to fix them |

---

## Quick Start (for people in a hurry)

```
1.  Create GCP project + enable Vertex AI + create GCS bucket
2.  Download service account JSON key
3.  Install: PostgreSQL 15+, Redis 7+, Python 3.11+, Node.js 18+
4.  Create postgres database "infoseek" with pgvector extension
5.  git clone / copy project files
6.  cd backend && python -m venv venv && source venv/bin/activate
7.  pip install -r requirements.txt
8.  Copy .env.example → .env and fill in GCP values
9.  alembic upgrade head
10. python scripts/seed_admin.py
11. uvicorn app.main:app --reload   (terminal 1)
12. celery -A app.tasks.celery_app worker --loglevel=info  (terminal 2)
13. cd ../frontend && npm install && npm start  (terminal 3)
14. Open http://localhost:3000 and log in as admin@studyrag.com / admin123
```

Detailed steps for each are in the individual guides above.
