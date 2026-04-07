.PHONY: help up down build logs shell-api shell-worker migrate test lint clean

help:
	@echo "StudyRAG — Development Commands"
	@echo ""
	@echo "  make up          Start all services"
	@echo "  make down        Stop all services"
	@echo "  make build       Rebuild images"
	@echo "  make logs        Tail all logs"
	@echo "  make logs-api    Tail API logs only"
	@echo "  make shell-api   Shell into API container"
	@echo "  make migrate     Run Alembic migrations"
	@echo "  make test        Run backend tests"
	@echo "  make lint        Run ruff linter"
	@echo "  make clean       Remove containers and volumes"
	@echo "  make seed        Create default admin user"

up:
	cp -n .env.example .env 2>/dev/null || true
	docker compose up -d

down:
	docker compose down

build:
	docker compose build --no-cache

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

shell-api:
	docker compose exec api bash

shell-worker:
	docker compose exec celery_worker bash

migrate:
	docker compose exec api alembic upgrade head

migrate-gen:
	@read -p "Migration message: " msg; \
	docker compose exec api alembic revision --autogenerate -m "$$msg"

test:
	docker compose exec api pytest tests/ -v --tb=short

lint:
	docker compose exec api ruff check app/ --fix

seed:
	docker compose exec api python scripts/seed_admin.py

clean:
	docker compose down -v --remove-orphans
	docker system prune -f

status:
	docker compose ps

restart-api:
	docker compose restart api

restart-worker:
	docker compose restart celery_worker
