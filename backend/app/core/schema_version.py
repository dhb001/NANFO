"""Explicit current-source compatibility, independent of settings and DB access.

This is not a claim that this source/image has passed deployment acceptance.
Historical release evidence and verifier targets remain separately versioned.
"""

# ADR-028 migration 0030 (schema remediation) is the current head.
CURRENT_SCHEMA = "0030"
# Verifier cases of earlier heads that appear in archived/accepted release matrices
# (0029 is the accepted ADR-027 release head); they stay exportable after the head moves.
HISTORICAL_MIGRATION_CASES = frozenset({
    "migration_0019", "migration_0021", "migration_0024", "migration_0027", "migration_0028", "migration_0029",
})
