"""Opt-in session-backed identities for synchronous REST contract tests.

JWT decoding, Redis session checks, and FastAPI authorization dependencies remain
production code. Only persistence is substituted with fakeredis/repository data.
"""

import json
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from types import SimpleNamespace

import fakeredis
from jose import jwt

from app.core.security import create_access_token, create_refresh_token
from app.modules.identity.sessions import SessionRepository

_current_identities: ContextVar["SessionIdentities"] = ContextVar("session_test_identities")


class SessionIdentities:
    def __init__(self):
        server = fakeredis.FakeServer()
        self.redis = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
        self._writer = fakeredis.FakeRedis(server=server, decode_responses=True)
        self.users = {}
        self.roles = {}
        self.permissions = {}
        self.org_id = uuid.UUID(int=100)
        self.workspaces = {}
        self.memberships = set()

    def issue(self, *, user_id, email, roles, permissions, org_id=None, workspace_id=None):
        sid = str(uuid.uuid4())
        scope = {"user_id": user_id, "sid": sid, "org_id": org_id, "workspace_id": workspace_id}
        refresh, _ = create_refresh_token(**scope)
        # Malformed-claim tests deliberately sign invalid scope. Their session is
        # otherwise valid; the production decoder must reject the access JWT.
        refresh_claims = jwt.get_unverified_claims(refresh)
        self._writer.set(
            SessionRepository.key(sid), json.dumps(SessionRepository._entry(refresh_claims, refresh)),
            exat=refresh_claims["exp"], nx=True,
        )
        user_uuid = uuid.UUID(user_id)
        self.users[user_uuid] = SimpleNamespace(user_id=user_uuid, email=email, is_active=True, display_name="Test User")
        self.roles[user_uuid] = list(roles)
        self.memberships.add((self.org_id, user_uuid))
        key = tuple(roles)
        if key in self.permissions and self.permissions[key] != permissions:
            raise ValueError("Conflicting permission definitions for a test role")
        self.permissions[key] = list(permissions) if roles else []
        return create_access_token(**scope, email=email, roles=roles, permissions=permissions)


def create_session_access_token(**kwargs):
    """Issue a JWT and register its session/current identity in the active fixture."""
    return _current_identities.get().issue(**kwargs)


def create_authorized_workspace() -> uuid.UUID:
    """Register a concrete workspace in the contract test's member organization."""
    identities = _current_identities.get()
    workspace_id = uuid.uuid4()
    identities.workspaces[workspace_id] = SimpleNamespace(
        workspace_id=workspace_id, org_id=identities.org_id, name="Test Workspace",
        description=None, created_at=datetime.now(UTC), deleted_at=None,
    )
    return workspace_id
