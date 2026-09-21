"""Append final receiver-health9–11 release evidence with prior pins untouched."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,'/home/DHB/Documents/NANFO')
from deploy import release_manifest as r

root=Path('/home/DHB/Documents/NANFO')
dest=root/'docs/project/CompletionProgram/DeploymentEvidence-ADR023-20260920'
snapshot=Path('/tmp/opencode/nanfo-adr023-frozen-yvofvp9n')
run=Path('/tmp/opencode/nanfo-deploy-verify-e5vhtnkm')
fleet='sha256:fac6029493690c0d60ee44117a393091aaa019b7dc579ac8784f2d86599007df'
def save(name,raw):
    path=dest/name
    if path.exists(): assert path.read_bytes()==raw
    else: r.publish(path,raw)
result=json.loads((run/'evidence/result.json').read_bytes())
assert result['core_passed'] and result['counts']=={'passed':29,'failed':0,'blocked':4,'pending':0}
images=result['cases']['locked_container_build']['detail']['images']
images={**images,'fleet':{'id':fleet,'os':'linux','architecture':'amd64'}}
save('health-final-images.json',r.canonical(images))
hashes=json.loads((snapshot/'source-snapshot.json').read_bytes())
safe={}
for name,digest in hashes.items():
    try: r.safe_name(name)
    except r.EvidenceError: continue
    safe[name]=digest
save('health-final-release-build.json',r.canonical({'image_id':images['api']['id'],'images':images,
    'source_sha256':safe,'host_site_packages_used':False,'scope':'Final receiver-health fixes;329 installed runtime files matched UID10001'}))
manifest=r.create_manifest(snapshot,dest,['health-final-release-build.json'])
save('health-final-release.json',r.canonical(manifest))
r.verify_manifest(manifest,snapshot,dest)
archive=dest/'health-final-distributed-evidence.tar'
if not archive.exists():
    digest=r.export_bundle(dest/'health-final-release.json',run,archive)
    r.verify_bundle_bytes(archive.read_bytes(),digest)
    save('health-final-distributed-archive-sha256.json',r.canonical({'sha256':digest}))
for name,source in (
    ('health-final-fleet-build-result.json','/tmp/opencode/nanfo-adr023-fleet-build-n2lugj0b/result.json'),
    ('health-final-fleet-build.log','/tmp/opencode/nanfo-adr023-fleet-build-n2lugj0b/build.log'),
    ('health-final-installed-smoke.json','/tmp/opencode/nanfo-adr023-health-final-probe-y_0p819t/result.json'),
    ('health-final-installed-probe.py','/tmp/opencode/adr023_health_final_probe.py'),
    ('health-final-installed-image-check.py','/tmp/opencode/adr023_health_final_image_check.py'),
    ('health-final-source-diff.py','/tmp/opencode/adr023_health_source_diff.py'),
): save(name,Path(source).read_bytes())
save('health-final-summary.json',r.canonical({'schema':'0027','distributed':result['counts'],
    'deployment_tests':{'passed':216,'failed':0},'receiver_client_regression_tests':{'passed':31,'failed':0},
    'installed_smoke_checks':{'passed':20,'failed':0},'prior_fleet_functional':{'passed':6,'failed':0,'reused':True},
    'fleet_source_diff':'health-final-fleet-source-diff.json','default_activation':False,'physical_qualification':False,
    'images':images,'source_drift':json.loads((dest/'health-final-distributed-source-drift.json').read_bytes())}))
save('health-final-export.py',Path(__file__).read_bytes())
save('health-final-checksums.json',r.canonical({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.iterdir()
    if p.is_file() and p.name.startswith('health-final-') and p.name!='health-final-checksums.json'}))
print(json.dumps({'counts':result['counts'],'backend':images['api']['id'],'fleet':fleet}))
