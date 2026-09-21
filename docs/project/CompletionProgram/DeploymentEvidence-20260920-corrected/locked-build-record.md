# ADR022 corrected asset-security source build

These are real Docker builds. Backend runtime COPY layers rebuilt from frozen
snapshot /tmp/opencode/nanfo-adr021-core-source-qtsyac8_ with source-map SHA256
2205f4c12ce7c6aed3f26be99d34a3ad441af46beeeb2c2279be186bb62b3678.
Production changes since preceding accepted0024 snapshot: asset_storage.py and
CampusModelAssetService in service.py. Asset tests also changed.

Backend: sha256:feecb2f3ad41554364df2ef745d0ace4de8be83cf96f1e90bc1417990a62eeba
Frontend: sha256:712b31ddc68c7757eb6eda1a54bbd9c83feab6bc8720ed675e36d331a1c116a6
Neo4j: sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7

Poetry locked main-install layer reused unchanged Docker cache:
poetry check --lock && poetry install --only main --no-root --no-interaction
followed by cached pip check. No reinstall/pull or host package substitution.
Frontend npm ci/lint/typecheck/production-build evidence and Neo4j image evidence:
docs/project/CompletionProgram/DeploymentEvidence-20260920/locked-build-record.md
and core-passed-result.json. Frontend, nginx, dependency and Neo4j source hashes
independently compared equal against that recorded snapshot before this rebuild.
