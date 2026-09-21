# ADR021 recovery source build record

These are real Docker builds. Frozen source snapshot:
/tmp/opencode/nanfo-adr021-core-source-skgtb461
Source-map SHA256: 28bb2a55da6c642971136c2f071c4023e0bd41e140dcec2f2061a4457a20493c

Backend: sha256:c2c35eeda19ca7448f865cf9e2f48069b2533aee0eeaf998cff7d81ad648820d
Frontend: sha256:0b276d12f471b356fa62881f7eb8063a32f4558a6d7b47883216278bb52cb0f7
Neo4j: sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7

Backend Poetry locked installation `poetry check --lock && poetry install --only main --no-root --no-interaction`
and pip check stage reused unchanged Docker cache; only deploy runtime COPY and
subsequent image metadata rebuilt. No host packages, builds/pulls during reuse.
Frontend npm ci/lint/typecheck/build was observed in original core build (durable
DeploymentEvidence-20260919/attempt4-result.json); its frozen sources are unchanged.
Neo4j uses the same pinned5.26.12 base with same-UID signal-forwarder wrapper;
actual clean shutdown and successful fresh recovery independently observed.
