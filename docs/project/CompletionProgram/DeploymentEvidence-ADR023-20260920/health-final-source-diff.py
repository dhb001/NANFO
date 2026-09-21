"""Exact snapshot diff supporting reuse of prior scoped fleet functional evidence."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,'/home/DHB/Documents/NANFO')
from deploy import release_manifest as r
old=Path('/tmp/opencode/nanfo-adr023-frozen-sufx7teb')
new=Path('/tmp/opencode/nanfo-adr023-frozen-yvofvp9n')
a=json.loads((old/'source-snapshot.json').read_bytes())
b=json.loads((new/'source-snapshot.json').read_bytes())
changed=[{'path':p,'before_sha256':a.get(p),'after_sha256':b.get(p)} for p in sorted(a.keys()|b.keys()) if a.get(p)!=b.get(p)]
prefixes=('backend/app/modules/telemetry/','backend/app/modules/identity/','backend/app/modules/network/',
          'backend/app/modules/organization/','backend/app/db/','backend/app/core/','backend/app/events/')
fixed={'backend/scripts/run_fleet_collector.py','backend/pyproject.toml','backend/poetry.lock','deploy/check_fleet_health.py',
       'deploy/compose.fleet.yaml','deploy/fleet.sources','deploy/Dockerfile.backend','deploy/entrypoint.py',
       'deploy/compose.yaml','deploy/volume_init.py','deploy/initialize.py'}
fleet_paths=sorted(p for p in a.keys()|b.keys() if (p.startswith(prefixes) and p.endswith('.py')) or p in fixed)
fleet_diff=[p for p in fleet_paths if a.get(p)!=b.get(p)]
assert not fleet_diff, fleet_diff
proof={'functional_evidence':'corrected-fleet-full-result.json','functional_image':'sha256:71b31676560195b54b5480507c71c857f064ebaa7cb3f0f793e2fcd8080c9e5a',
       'current_image':'sha256:fac6029493690c0d60ee44117a393091aaa019b7dc579ac8784f2d86599007df',
       'exact_snapshot_changes':changed,'unchanged_fleet_runtime_inputs':{p:b[p] for p in fleet_paths},
       'changed_fleet_runtime_inputs':fleet_diff,'reuse_scope':'Prior six real fleet CLI gates remain scoped historical evidence; unchanged listed owning paths support reuse, not new physical qualification.'}
dest=Path('/home/DHB/Documents/NANFO/docs/project/CompletionProgram/DeploymentEvidence-ADR023-20260920/health-final-fleet-source-diff.json')
raw=r.canonical(proof)
if dest.exists(): assert dest.read_bytes()==raw
else: r.publish(dest,raw)
print(json.dumps({'changed_paths':[x['path'] for x in changed],'unchanged_fleet_inputs':len(fleet_paths),'fleet_diff':fleet_diff}))
