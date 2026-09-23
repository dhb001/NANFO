.PHONY: up down migrate migrate-down dev test test-unit test-integration lint

# ── Infrastructure ────────────────────────────────────────────────────────────
up:
	../scripts/dev-start.sh

down:
	docker compose down

# ── Database ─────────────────────────────────────────────────────────────────
migrate:
	alembic -c alembic/alembic.ini upgrade head

migrate-down:
	alembic -c alembic/alembic.ini downgrade -1

# ── Development ───────────────────────────────────────────────────────────────
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	pytest

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

# ── Quality ───────────────────────────────────────────────────────────────────
lint:
	ruff check app/ tests/
