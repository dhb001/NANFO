"""Actual PostgreSQL WHERE-before-LIMIT and current multi-tenant authorization."""

import os
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.modules.alert.repository import AlertRepository
from app.modules.alert.service import AlertService
from app.modules.network.models import Network
from app.modules.organization.models import Organization, OrgMember, Workspace
from tests.alert_support import ACTOR, NETWORK, ORG, START, WORKSPACE
from tests.integration.test_alert_postgres import seed_scope, sessions as alert_sessions

sessions = alert_sessions

pytestmark = pytest.mark.skipif(not os.environ.get("ALERT_TEST_DSN"), reason="ALERT_TEST_DSN not configured")
OTHER_NETWORK, OTHER_WORKSPACE, OTHER_ORG = (uuid.UUID(int=i) for i in (8001, 8002, 8003))


async def test_filters_find_old_active_behind_200_newer_resolved_and_other_network(sessions):
    await seed_scope(sessions)
    async with sessions() as db:
        db.add(Network(network_id=OTHER_NETWORK, workspace_id=WORKSPACE, name="Other authorized network"))
        repo = AlertRepository(db)
        for i in range(202):
            row = await repo.create_generated(alert_id=uuid.UUID(int=9000 + i), alert_key=f"incident-{i}",
                source="telemetry", severity="warning", correlation_id=uuid.UUID(int=77),
                payload={"scope": {"workspace_id": str(WORKSPACE), "network_id": str(NETWORK), "org_id": str(ORG)}},
                generated_event_id=uuid.UUID(int=19000 + i), created_at=START + timedelta(seconds=i))
            if i > 0:
                row.status = "resolved"
                # Make timestamp dirty too, avoiding the ORM onupdate clock.
                row.updated_at = START + timedelta(seconds=i, microseconds=1)
        await repo.create_generated(alert_id=uuid.UUID(int=22000), alert_key="other-network", source="telemetry",
            severity="warning", correlation_id=uuid.UUID(int=77), payload={"network_id": str(OTHER_NETWORK)},
            generated_event_id=uuid.UUID(int=23000), created_at=START + timedelta(days=1))
        await db.commit()
    args = dict(status_filter=None, severity_filter=None, source_filter=None, correlation_id_filter=None,
                search_filter=None, limit=200, actor_user_id=str(ACTOR))
    async with sessions() as db:
        svc = AlertService(db=db, redis=None)
        unfiltered = await svc.list_alerts(**args)
        # ADR-028: the total is every authorized match (202 incidents + other network).
        assert unfiltered.total == 203 and len(unfiltered.items) == 200
        assert unfiltered.status_counts == {"active": 2, "acknowledged": 0, "resolved": 201}
        assert "incident-0" not in {r.alert_key for r in unfiltered.items}
        active = await svc.list_alerts(**{**args, "status_filter": "active"}, workspace_id_filter=WORKSPACE,
                                       network_id_filter=NETWORK)
        assert [r.alert_key for r in active.items] == ["incident-0"]
        assert active.status_counts == {"active": 1, "acknowledged": 0, "resolved": 0}
        searched = await svc.list_alerts(**{**args, "search_filter": "incident-0", "severity_filter": "warning",
                                           "source_filter": "telemetry"}, network_id_filter=NETWORK)
        assert [r.alert_key for r in searched.items] == ["incident-0"]
        # Scope filtering itself precedes LIMIT, even for another authorized network.
        selected = await svc.list_alerts(**{**args, "limit": 1}, network_id_filter=NETWORK)
        assert selected.items[0].alert_key == "incident-201"
        assert unfiltered.items[0].alert_key == "other-network"


async def test_current_membership_claims_and_mismatched_network_selection(sessions):
    await seed_scope(sessions)
    async with sessions() as db:
        db.add(Organization(org_id=OTHER_ORG, name="Foreign", slug="foreign"))
        await db.flush()
        db.add(Workspace(workspace_id=OTHER_WORKSPACE, org_id=OTHER_ORG, name="Foreign"))
        await db.flush()
        db.add(Network(network_id=OTHER_NETWORK, workspace_id=OTHER_WORKSPACE, name="Foreign"))
        await db.commit()
    args = dict(status_filter=None, severity_filter=None, source_filter=None, correlation_id_filter=None,
                search_filter=None, limit=200, actor_user_id=str(ACTOR))
    for selection in [dict(workspace_id_filter=OTHER_WORKSPACE), dict(network_id_filter=OTHER_NETWORK),
                      dict(workspace_id_filter=WORKSPACE, network_id_filter=OTHER_NETWORK),
                      dict(requested_workspace_id=OTHER_WORKSPACE, workspace_id_filter=WORKSPACE),
                      dict(claim_org_id=OTHER_ORG, network_id_filter=NETWORK)]:
        async with sessions() as db:
            with pytest.raises(HTTPException) as denied:
                await AlertService(db=db, redis=None).list_alerts(**args, **selection)
            assert denied.value.status_code == 403
    async with sessions() as db:
        await db.execute(update(OrgMember).where(OrgMember.user_id == ACTOR).values(deleted_at=START))
        await db.commit()
    async with sessions() as db:
        with pytest.raises(HTTPException) as denied:
            await AlertService(db=db, redis=None).list_alerts(**args, workspace_id_filter=WORKSPACE, network_id_filter=NETWORK)
        assert denied.value.status_code == 403
