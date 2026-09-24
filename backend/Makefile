.PHONY: up down migrate migrate-down dev test test-unit test-integration lint check

# Python tooling always runs inside the locked Poetry environment (Python 3.12.14,
# see .python-version) so local results match CI. Paths below mirror
# .github/workflows/quality.yml exactly.
POETRY_RUN := poetry run
ALEMBIC := $(POETRY_RUN) alembic -c alembic/alembic.ini
LINT_PATHS := app tests scripts
PORTABLE_MARKERS := not private_artifacts

# ── Infrastructure (Docker only; no Python tooling) ──────────────────────────
up:
	../scripts/dev-start.sh

down:
	../scripts/dev-stop.sh

# ── Database ─────────────────────────────────────────────────────────────────
migrate:
	$(ALEMBIC) upgrade head

migrate-down:
	$(ALEMBIC) downgrade -1

# ── Development (loopback only; never expose the dev server) ────────────────
dev:
	$(POETRY_RUN) uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	$(POETRY_RUN) pytest

test-unit:
	$(POETRY_RUN) pytest tests/unit/ -v

test-integration:
	$(POETRY_RUN) pytest tests/integration/ -v

# ── Quality ───────────────────────────────────────────────────────────────────
lint:
	$(POETRY_RUN) ruff check $(LINT_PATHS)

# Same lint paths and portable test selection as the CI backend job. Tests that
# need the ignored ai-engine/artifacts store are excluded; run them with `make test`.
check:
	$(POETRY_RUN) ruff check $(LINT_PATHS)
	$(POETRY_RUN) pytest tests/unit tests/integration -m "$(PORTABLE_MARKERS)" -q
