# 13 — Running in Production

This guide covers hardening and running the application on a production Linux server (Ubuntu 22.04). It does not cover cloud-specific deployment (GKE, Cloud Run, etc.) — just a straightforward single-server setup.

---

## Security Hardening Before Deploying

### 1. Change all default secrets

```bash
# Generate a strong SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Change:
- `SECRET_KEY` — generate a fresh random value
- `POSTGRES_PASSWORD` — change from `root` to a strong password
- `admin@studyrag.com` password — change immediately after first login

### 2. Set APP_ENV=production

```env
APP_ENV=production
```

This disables the Swagger UI (`/docs` and `/redoc`) so your API schema is not publicly exposed.

### 3. Restrict CORS_ORIGINS

```env
CORS_ORIGINS=["https://yourdomain.com"]
```

Never use `["*"]` in production — this allows any website to make API calls on behalf of your users.

### 4. PostgreSQL access

Edit `/etc/postgresql/15/main/pg_hba.conf` to only allow localhost connections:
```
local   all   postgres   peer
host    all   all        127.0.0.1/32   scram-sha-256
```

Then restart: `sudo systemctl restart postgresql`

### 5. Redis access

Edit `/etc/redis/redis.conf`:
```
bind 127.0.0.1
requirepass your-strong-redis-password
```

If you add a Redis password, update the URLs in `.env`:
```
REDIS_URL=redis://:yourpassword@localhost:6379/0
CELERY_BROKER_URL=redis://:yourpassword@localhost:6379/1
CELERY_RESULT_BACKEND=redis://:yourpassword@localhost:6379/2
```

### 6. Protect the service account key

```bash
chmod 600 /path/to/service-account-key.json
chown youruser:youruser /path/to/service-account-key.json
```

---

## Running with systemd

systemd manages processes as services — auto-starts them on boot and restarts them if they crash.

### Backend API Service

Create `/etc/systemd/system/studyrag-api.service`:

```ini
[Unit]
Description=StudyRAG FastAPI Backend
After=network.target postgresql.service redis.service

[Service]
Type=exec
User=youruser
WorkingDirectory=/path/to/rag-app/backend
Environment=PATH=/path/to/rag-app/backend/venv/bin
ExecStart=/path/to/rag-app/backend/venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 2 \
    --log-level info
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Celery Worker Service

Create `/etc/systemd/system/studyrag-worker.service`:

```ini
[Unit]
Description=StudyRAG Celery Worker
After=network.target redis.service studyrag-api.service

[Service]
Type=exec
User=youruser
WorkingDirectory=/path/to/rag-app/backend
Environment=PATH=/path/to/rag-app/backend/venv/bin
ExecStart=/path/to/rag-app/backend/venv/bin/celery \
    -A app.tasks.celery_app worker \
    --loglevel=info \
    --concurrency=2
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Celery Beat Service (Scheduled Tasks)

Celery Beat runs scheduled tasks (like hourly session expiry). Create `/etc/systemd/system/studyrag-beat.service`:

```ini
[Unit]
Description=StudyRAG Celery Beat Scheduler
After=network.target redis.service

[Service]
Type=exec
User=youruser
WorkingDirectory=/path/to/rag-app/backend
Environment=PATH=/path/to/rag-app/backend/venv/bin
ExecStart=/path/to/rag-app/backend/venv/bin/celery \
    -A app.tasks.celery_app beat \
    --loglevel=info
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Enable and Start All Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable studyrag-api studyrag-worker studyrag-beat
sudo systemctl start studyrag-api studyrag-worker studyrag-beat

# Check status
sudo systemctl status studyrag-api
sudo journalctl -u studyrag-api -f    # follow logs
```

---

## Nginx Reverse Proxy

Nginx sits in front of the FastAPI server and handles SSL, compression, and static file serving.

Install:
```bash
sudo apt install nginx -y
```

Create `/etc/nginx/sites-available/studyrag`:

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Streaming support
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300;
        chunked_transfer_encoding on;
    }

    # React frontend (static files)
    location / {
        root /path/to/rag-app/frontend/build;
        try_files $uri $uri/ /index.html;
        
        # Cache static assets
        location ~* \.(js|css|png|jpg|ico|woff2)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
}
```

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/studyrag /etc/nginx/sites-enabled/
sudo nginx -t    # test config
sudo systemctl reload nginx
```

### SSL Certificate (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d yourdomain.com
```

Certbot automatically adds SSL configuration and sets up auto-renewal.

---

## Frontend Build

```bash
cd frontend

# Set production API URL
echo "REACT_APP_API_URL=https://yourdomain.com" > .env.production

npm run build
```

This creates `frontend/build/` — a static directory that Nginx serves directly. No Node.js needed at runtime for the frontend.

---

## Monitoring

### View Logs

```bash
# API logs
sudo journalctl -u studyrag-api -f

# Worker logs
sudo journalctl -u studyrag-worker -f

# nginx access logs
sudo tail -f /var/log/nginx/access.log
```

### Prometheus Metrics

The backend exposes Prometheus metrics at `/metrics` via `prometheus-fastapi-instrumentator`.

You can scrape this with a Prometheus instance and visualize with Grafana. Basic metrics include:
- Request count per endpoint
- Request latency histograms
- In-flight requests

### Celery Flower (Task Monitor)

Flower is a Celery task monitoring web UI:

```bash
source venv/bin/activate
celery -A app.tasks.celery_app flower --port=5555
```

Access at `http://localhost:5555`. Shows active tasks, task history, worker status.

---

## Database Backups

```bash
# Daily backup
pg_dump -U postgres infoseek | gzip > /backups/infoseek_$(date +%Y%m%d).sql.gz

# Restore
gunzip < /backups/infoseek_20240101.sql.gz | psql -U postgres infoseek
```

Set this up as a daily cron job:
```bash
# Edit crontab
crontab -e

# Add this line (backs up at 2 AM daily)
0 2 * * * pg_dump -U postgres infoseek | gzip > /backups/infoseek_$(date +\%Y\%m\%d).sql.gz
```

---

## Upgrading the Application

```bash
# 1. Pull new code
cd /path/to/rag-app
git pull

# 2. Install any new Python packages
cd backend && source venv/bin/activate && pip install -r requirements.txt

# 3. Run database migrations
alembic upgrade head

# 4. Rebuild frontend
cd ../frontend && npm install && npm run build

# 5. Restart services
sudo systemctl restart studyrag-api studyrag-worker studyrag-beat
```

---

## Production Checklist

- [ ] `APP_ENV=production`
- [ ] Strong random `SECRET_KEY`
- [ ] PostgreSQL password changed
- [ ] Redis password set
- [ ] Service account key protected (chmod 600)
- [ ] CORS restricted to your domain
- [ ] SSL certificate installed
- [ ] systemd services enabled and running
- [ ] Admin password changed
- [ ] Database backup scheduled
- [ ] Logs monitored
