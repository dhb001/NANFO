"""DB-backed acceptance scripts demote actors only to roles the 0030 CHECK admits (ADR-028).

``ck_org_members_org_role`` closes ``org_members.org_role`` to Admin/Operator/Read-Only, so
a demotion to any other literal (formerly ``'Viewer'``) fails on a migrated database
before the script's authorization assertion runs. Read-Only keeps the intended 403 path.
"""

import re
from pathlib import Path

import pytest

from app.modules.organization.service import _WRITE_ROLES, ORG_ROLES

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
ROLE_LITERAL = re.compile(r"org_role\s*=\s*'([^']*)'")


@pytest.mark.parametrize("script", ["verify_model_diagnostics.py", "accept_continuous_feed.py",
                                    "verify_experimental_lab.py"])
def test_demotions_use_a_role_admitted_by_ck_org_members_org_role(script):
    roles = ROLE_LITERAL.findall((SCRIPTS / script).read_text(encoding="utf-8"))
    assert roles and set(roles) <= set(ORG_ROLES), roles
    assert "Read-Only" in roles and "Read-Only" not in _WRITE_ROLES
