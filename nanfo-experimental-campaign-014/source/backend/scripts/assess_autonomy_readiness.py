"""Run from backend with PYTHONPATH=. No live lab or deployment side effects."""

from app.modules.autonomy.readiness_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
