# 02 — Prerequisites & Accounts

Before writing a single line of configuration, you need several things installed and two online accounts created. This guide covers all of them.

---

## 1. Operating System

The project is developed and tested on **Ubuntu/Debian Linux**. It also works on macOS. Windows requires WSL2 (Windows Subsystem for Linux) — run everything inside a WSL2 Ubuntu shell.

---

## 2. Software to Install

### Python 3.11 or 3.12

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev -y

# Verify
python3 --version   # should print Python 3.12.x
```

> **Why 3.11+?** The codebase uses `match` statements, `asyncio.to_thread`, and type hints that require Python 3.11+.

### Node.js 18 or 20 (LTS)

```bash
# Ubuntu — using NodeSource
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install nodejs -y

# Verify
node --version   # v20.x.x
npm --version    # 10.x.x
```

> **Learn more:** [Node.js official downloads](https://nodejs.org/en/download)

### PostgreSQL 15 (or newer)

```bash
# Ubuntu
sudo apt install postgresql postgresql-contrib -y

# Start and enable
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Verify
psql --version   # psql (PostgreSQL) 15.x
```

> **Learn more:** [PostgreSQL downloads](https://www.postgresql.org/download/)

### Redis 7

```bash
# Ubuntu
sudo apt install redis-server -y
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Verify
redis-cli ping   # should respond: PONG
```

> **What Redis is for:** Acts as the message broker between the web server and Celery background workers. Also used for caching API responses.

### Build tools (needed for some Python packages)

```bash
sudo apt install build-essential libssl-dev libffi-dev -y
sudo apt install libpq-dev -y    # for psycopg2
sudo apt install poppler-utils -y  # for PDF tools (optional)
```

### Git

```bash
sudo apt install git -y
```

---

## 3. Accounts to Create

### Google Cloud Platform Account

You need a GCP account with billing enabled. You get $300 free credit when you sign up with a new account.

**Steps:**
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Sign in with your Google account (or create one)
3. Click "Try for free" and add billing information (you won't be charged within the free tier)
4. Once inside the console, note your **project ID** (shown in the top dropdown) — you'll need it

> **Cost estimate for development:** Using Gemini Flash heavily costs ~$1–5/month. Gemini Pro is ~$10–30/month depending on documents processed. GCS storage is under $1/month for typical volumes.

> **Learn more:** [GCP Getting Started](https://cloud.google.com/docs/get-started)

---

## 4. What You'll Create in GCP (covered in next guide)

- Enable the Vertex AI API
- Enable the Cloud Storage API
- Enable the Cloud Vision API (for OCR on scanned PDFs)
- Create a GCS bucket for storing uploaded PDFs
- Create a service account and download its JSON key

All of this is covered step-by-step in [03 — GCP Setup](./03-gcp-setup.md).

---

## 5. Version Compatibility Matrix

| Component | Minimum | Tested On |
|-----------|---------|-----------|
| Python | 3.11 | 3.12 |
| Node.js | 18 | 20 |
| PostgreSQL | 14 | 15 |
| pgvector | 0.6.0 | 0.6.0 |
| Redis | 6 | 7 |
| Celery | 5.3 | 5.4 |
| FastAPI | 0.100 | 0.111 |

---

## Summary Checklist

Before moving to the next step, confirm each item:

- [ ] Python 3.11+ installed (`python3 --version`)
- [ ] Node.js 18+ installed (`node --version`)
- [ ] PostgreSQL running (`sudo systemctl status postgresql`)
- [ ] Redis running (`redis-cli ping` returns `PONG`)
- [ ] GCP account created with billing enabled
- [ ] GCP project created and project ID noted
