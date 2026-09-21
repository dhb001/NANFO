"""Explicit current-source compatibility, independent of settings and DB access.

This is not a claim that this source/image has passed deployment acceptance.
Historical release evidence and verifier targets remain separately versioned.
"""

CURRENT_SCHEMA = "0029"
HISTORICAL_MIGRATION_CASES = frozenset({
    "migration_0019", "migration_0021", "migration_0024", "migration_0027", "migration_0028",
})
