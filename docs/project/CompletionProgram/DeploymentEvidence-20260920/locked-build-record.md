# ADR022 observed source builds

These are real Docker builds from frozen source snapshots, not historical image aliases.
Backend final snapshot /tmp/opencode/nanfo-adr021-core-source-pjh8ee_o:
a364b9836792bd5cb1b66550e4f42489eb8fbe28cd3e0deb815c2cc87e19348f.
Poetry dependency layers cached unchanged: poetry check --lock && poetry install --only main --no-root --no-interaction; final pip check cached.
Frontend npm ci cached unchanged; lint/typecheck/production build executed successfully
from /tmp/opencode/nanfo-adr021-core-source-zy_z16m3, with identical final frontend source hashes.
Neo4j wrapper unchanged since actual recovery acceptance recorded under DeploymentRecovery-20260919.

Backend: sha256:0876615dee3c7faf11c50ca42fdb27b75242f099913983d4d0747b83df212221
Frontend: sha256:712b31ddc68c7757eb6eda1a54bbd9c83feab6bc8720ed675e36d331a1c116a6
Neo4j: sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7
