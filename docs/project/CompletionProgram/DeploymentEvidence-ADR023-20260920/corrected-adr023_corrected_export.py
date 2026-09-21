"""Append corrected campaign evidence, never replace the initial release records."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path('/home/DHB/Documents/NANFO')
sys.path.insert(0, str(ROOT))
from deploy import release_manifest as r

dest = ROOT / 'docs/project/CompletionProgram/DeploymentEvidence-ADR023-20260920'
snapshot = Path('/tmp/opencode/nanfo-adr023-frozen-sufx7teb')
run = Path('/tmp/opencode/nanfo-deploy-verify-tmi4p8hn')
fleet_image = 'sha256:71b31676560195b54b5480507c71c857f064ebaa7cb3f0f793e2fcd8080c9e5a'

def save(name, raw):
    path = dest / name
    if path.exists():
        assert path.read_bytes() == raw
    else:
        r.publish(path, raw)

for label, directory in (
    ('corrected-fleet-build', '/tmp/opencode/nanfo-adr023-fleet-build-_rh6sr9u'),
    ('corrected-snmp', '/tmp/opencode/nanfo-adr023-snmp-probe-gry4xkpt'),
    ('corrected-fleet-attempt1', '/tmp/opencode/nanfo-adr023-fleet-full-6c85w2ma'),
    ('corrected-fleet-full', '/tmp/opencode/nanfo-adr023-fleet-full-ra5swbre'),
):
    directory = Path(directory)
    save(label + '-result.json', (directory / 'result.json').read_bytes())
    save(label + '-build.log', (directory / 'build.log').read_bytes())
    if (directory / 'probe.py').exists():
        save(label + '-probe.py', (directory / 'probe.py').read_bytes())
for name in ('adr023_fleet_full_run.py','adr023_snmp_build.py','adr023_corrected_export.py'):
    save('corrected-' + name, Path('/tmp/opencode',name).read_bytes())
hashes = json.loads((snapshot / 'source-snapshot.json').read_bytes())
runtime = {str('/opt/nanfo/' + name): digest for name,digest in hashes.items()
           if name.endswith('.py') and not Path(name).name.startswith('test_') and 'tests' not in Path(name).parts
           and name != 'deploy/verify.py' and name.startswith(('backend/app/','backend/scripts/','backend/alembic/','emulation/','deploy/'))}
if not (dest / 'corrected-fleet-parity.json').exists():
    output = subprocess.check_output(['docker','run','--rm','--pull=never','-i','--network','none','--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--entrypoint','python',fleet_image,'-c',
        "import hashlib,json,sys;from pathlib import Path; expected=json.load(sys.stdin);bad=[p for p,h in expected.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];print(json.dumps({'files':len(expected),'matched':not bad}));sys.exit(bool(bad))"],
        input=json.dumps(runtime).encode(),timeout=60)
    save('corrected-fleet-parity.json',output)
result = json.loads((run / 'evidence/result.json').read_bytes())
images = result['cases']['locked_container_build']['detail']['images']
save('corrected-images.json', r.canonical({**images,'fleet':{'id':fleet_image,'os':'linux','architecture':'amd64'}}))
safe_hashes = {}
for name,digest in hashes.items():
    try: r.safe_name(name)
    except r.EvidenceError: continue
    safe_hashes[name]=digest
save('corrected-release-build.json',r.canonical({'image_id':images['api']['id'],'images':images,
    'source_sha256':safe_hashes,'host_site_packages_used':False,'scope':'frozen corrected source; installed UID10001 parity checked'}))
manifest = r.create_manifest(snapshot,dest,['corrected-release-build.json'])
save('corrected-release.json',r.canonical(manifest))
r.verify_manifest(manifest,snapshot,dest)
archive = dest / 'corrected-distributed-evidence.tar'
if not archive.exists():
    digest = r.export_bundle(dest/'corrected-release.json',run,archive)
    r.verify_bundle_bytes(archive.read_bytes(),digest)
    save('corrected-distributed-archive-sha256.json',r.canonical({'sha256':digest}))
checksums={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.iterdir()
           if p.is_file() and p.name.startswith('corrected-') and p.name!='corrected-checksums.json'}
save('corrected-checksums.json',r.canonical(checksums))
print(json.dumps({'counts':result['counts'],'images':{k:images[k]['id'] for k in ('api','gateway','neo4j')},'fleet':fleet_image}))
