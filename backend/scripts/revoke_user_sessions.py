"""Revoke every session of one user (ADR-028 C9); optionally deactivate the account first.

From backend:
    poetry run python -m scripts.revoke_user_sessions --user-id <uuid> [--reason operator_request]
    poetry run python -m scripts.revoke_user_sessions --email user@example.com --deactivate

Uses the application's configured PostgreSQL and Redis (environment/.env).
Every run is audited (``auth.user.sessions_revoked``; ``auth.user.deactivated``
when the account changed). Output is a single JSON line; tokens and secrets are
never printed. Exit status: 0 success, 2 usage/user error, 3 dependency outage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import DependencyUnavailableError  # noqa: E402

_REASONS = ("operator_request", "password_changed", "role_downgrade")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = value.add_mutually_exclusive_group(required=True)
    target.add_argument("--user-id", type=uuid.UUID)
    target.add_argument("--email")
    value.add_argument("--deactivate", action="store_true",
                       help="set is_active=false, then revoke (reason 'deactivated')")
    value.add_argument("--reason", choices=_REASONS, default="operator_request",
                       help="audit reason when not deactivating")
    value.add_argument("--actor-id", type=uuid.UUID, help="operator identity recorded in the audit row")
    return value


async def execute(args, *, sessions=None, redis=None) -> dict:
    """Run the revocation; ``sessions``/``redis`` are injectable for tests."""
    from app.db.postgres import AsyncSessionLocal
    from app.modules.identity.repository import UserRepository
    from app.modules.identity.service import AuthService, IdentityAccountService

    owns_redis = redis is None
    if owns_redis:
        from app.db.redis import close_redis, get_redis_client, init_redis

        await init_redis()
        redis = get_redis_client()
    session_factory = sessions or AsyncSessionLocal
    correlation_id = str(uuid.uuid4())
    try:
        async with session_factory() as db:
            user_id = args.user_id
            if user_id is None:
                user = await UserRepository(db).get_by_email(args.email)
                if user is None:
                    raise LookupError("User not found.")
                user_id = user.user_id
            if args.deactivate:
                revoked = await IdentityAccountService(db, redis).deactivate_user(
                    user_id, actor_id=args.actor_id, correlation_id=correlation_id,
                )
                reason = "deactivated"
            else:
                if await UserRepository(db).get_by_id(user_id) is None:
                    raise LookupError("User not found.")
                reason = args.reason
                revoked = await AuthService(db, redis).revoke_user_sessions(
                    user_id, reason=reason, correlation_id=correlation_id, actor_id=args.actor_id,
                )
    finally:
        if owns_redis:
            await close_redis()
    return {"user_id": str(user_id), "reason": reason, "revoked_sessions": revoked,
            "correlation_id": correlation_id}


def main(argv=None) -> int:
    from redis.exceptions import RedisError
    from sqlalchemy.exc import SQLAlchemyError

    args = parser().parse_args(argv)
    try:
        result = asyncio.run(execute(args))
    except LookupError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except DependencyUnavailableError as exc:
        print(json.dumps({"error": "dependency unavailable", "dependency": exc.dependency}), file=sys.stderr)
        return 3
    except (RedisError, SQLAlchemyError, OSError) as exc:
        print(json.dumps({"error": "dependency unavailable", "error_type": type(exc).__name__}), file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
