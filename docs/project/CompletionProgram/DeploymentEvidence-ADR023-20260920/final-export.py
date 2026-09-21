"""Append final corrected distributed acceptance without overwriting quota failure."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,'/home/DHB/Documents/NANFO')
from deploy import release_manifest as r

root=Path('/home/DHB/Documents/NANFO')
dest=root/'docs/project/CompletionProgram/DeploymentEvidence-ADR023-20260920'
snapshot=Path('/tmp/opencode/nanfo-adr023-frozen-sufx7teb')
run=Path('/tmp/opencode/nanfo-deploy-verify-b_fzalg0')
def save(name,raw):
    path=dest/name
    if path.exists(): assert path.read_bytes()==raw
    else: r.publish(path,raw)
result=json.loads((run/'evidence/result.json').read_bytes())
assert result['core_passed'] and result['counts']=={'passed':29,'failed':0,'blocked':4,'pending':0}
images=result['cases']['locked_container_build']['detail']['images']
earlier=json.loads((dest/'corrected-images.json').read_bytes())
assert all(images[name]==spec for name,spec in earlier.items() if name!='fleet')
save('final-images.json',r.canonical(earlier))
r.verify_manifest(json.loads((dest/'corrected-release.json').read_bytes()),snapshot,dest)
archive=dest/'final-distributed-evidence.tar'
if not archive.exists():
    digest=r.export_bundle(dest/'corrected-release.json',run,archive)
    r.verify_bundle_bytes(archive.read_bytes(),digest)
    save('final-distributed-archive-sha256.json',r.canonical({'sha256':digest}))
save('final-acceptance-summary.json',r.canonical({
    'schema':'0027','distributed':result['counts'],'fleet_worker':{'passed':6,'failed':0,'blocked':0},
    'packaged_snmp':{'passed':1,'failed':0,'blocked':0},'fleet_packages':{'passed':1,'failed':0,'blocked':0},
    'earlier_singleton_core':'retained_original_28pass_0fail_5blocked_not_rerun',
    'quota_attempt':'corrected-distributed-result.json;19pass_2fail_12blocked',
    'production_source_drift':json.loads((dest/'final-distributed-source-drift.json').read_bytes()),
    'images':earlier,
}))
save('final-export.py',Path(__file__).read_bytes())
save('private-backup-relocation-summary.json',r.canonical({
    'runs':['nanfo-deploy-verify-d_iukq6u','nanfo-deploy-verify-ui7t5pi2','nanfo-deploy-verify-tmi4p8hn'],
    'protected_destination':'deploy/state/adr023-private-evidence','all_file_hashes_verified_before_source_removal':True,
    'archive_manifests_authenticated':True,'shared_resources_or_other_agents_files_removed':False,
    'cause':'EDQUOT(errno122)_on_tmpfs_during_archive_authentication',
}))
save('final-checksums.json',r.canonical({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.iterdir()
    if p.is_file() and (p.name.startswith('final-') or p.name=='private-backup-relocation-summary.json')
    and p.name!='final-checksums.json'}))
print(json.dumps({'counts':result['counts'],'image':images['api']['id'],'fleet':earlier['fleet']['id']}))
