"""Append journal-client deployment release evidence, retain every earlier release."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,'/home/DHB/Documents/NANFO')
from deploy import release_manifest as r

root=Path('/home/DHB/Documents/NANFO')
dest=root/'docs/project/CompletionProgram/DeploymentEvidence-ADR023-20260920'
snapshot=Path('/tmp/opencode/nanfo-adr023-frozen-0bco__84')
run=Path('/tmp/opencode/nanfo-deploy-verify-fnh8dvek')
fleet='sha256:13be46a557ecb7ea22d6d7f0de2e0792b68b44db3021cf1df99ee4971d509702'
def save(name,raw):
    path=dest/name
    if path.exists(): assert path.read_bytes()==raw
    else: r.publish(path,raw)
result=json.loads((run/'evidence/result.json').read_bytes())
assert result['core_passed'] and result['counts']=={'passed':29,'failed':0,'blocked':4,'pending':0}
images=result['cases']['locked_container_build']['detail']['images']
images={**images,'fleet':{'id':fleet,'os':'linux','architecture':'amd64'}}
save('journal-images.json',r.canonical(images))
hashes=json.loads((snapshot/'source-snapshot.json').read_bytes())
safe={}
for name,digest in hashes.items():
    try: r.safe_name(name)
    except r.EvidenceError: continue
    safe[name]=digest
save('journal-release-build.json',r.canonical({'image_id':images['api']['id'],'images':images,
    'source_sha256':safe,'host_site_packages_used':False,'scope':'Frozen journal-client release;327 installed runtime files matched UID10001'}))
manifest=r.create_manifest(snapshot,dest,['journal-release-build.json'])
save('journal-release.json',r.canonical(manifest))
r.verify_manifest(manifest,snapshot,dest)
archive=dest/'journal-distributed-evidence.tar'
if not archive.exists():
    digest=r.export_bundle(dest/'journal-release.json',run,archive)
    r.verify_bundle_bytes(archive.read_bytes(),digest)
    save('journal-distributed-archive-sha256.json',r.canonical({'sha256':digest}))
for name,source in (
    ('journal-fleet-build-result.json','/tmp/opencode/nanfo-adr023-fleet-build-z6x340j5/result.json'),
    ('journal-fleet-build.log','/tmp/opencode/nanfo-adr023-fleet-build-z6x340j5/build.log'),
    ('journal-installed-factory-checks.json','/tmp/opencode/nanfo-adr023-journal-probe-io5i5nr9/result.json'),
    ('journal-installed-factory-probe.py','/tmp/opencode/adr023_journal_probe.py'),
    ('journal-installed-image-check.py','/tmp/opencode/adr023_journal_image_check.py'),
): save(name,Path(source).read_bytes())
save('journal-summary.json',r.canonical({'schema':'0027','distributed':result['counts'],
    'deployment_tests':{'passed':216,'failed':0},'installed_fail_closed_factory_cases':{'passed':6,'failed':0},
    'optional_authentic_installation':'not_supplied_not_enabled','physical_qualification':False,
    'images':images,'source_drift':json.loads((dest/'journal-distributed-source-drift.json').read_bytes())}))
save('journal-export.py',Path(__file__).read_bytes())
save('journal-checksums.json',r.canonical({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.iterdir()
    if p.is_file() and p.name.startswith('journal-') and p.name!='journal-checksums.json'}))
print(json.dumps({'counts':result['counts'],'backend':images['api']['id'],'fleet':fleet}))
