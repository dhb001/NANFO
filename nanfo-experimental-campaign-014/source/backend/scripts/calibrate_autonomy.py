"""Read-only measured holdout diagnostics, not a calibration installation."""

from app.modules.autonomy.readiness_cli import calibration_main

if __name__ == "__main__":
    raise SystemExit(calibration_main())
