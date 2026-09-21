"""Copy actual pinned benchmark inputs; qualify offline with unchanged installed registry."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

os.umask(0o077)
source=Path('/tmp/opencode/nanfo-adr024-evaluation-002')
installation=Path('/tmp/opencode/nanfo-adr024-installation-check-3y1h6uhj')
snapshot=Path('/tmp/opencode/nanfo-adr023-frozen-ei7ulj7m')
root=Path(tempfile.mkdtemp(prefix='nanfo-adr024-deploy-qualification-',dir='/tmp/opencode'))
artifacts=root/'artifacts'
artifacts.mkdir(mode=0o700)
observations=root/'observations'
observations.mkdir(mode=0o700)
raw=(installation/'registry.json').read_bytes()
registry=json.loads(raw)
refs=[registry[name] for name in ('checkpoint','parent_checkpoint','plan','selection','report','lineage','seed_audit')]
refs += [ref for session in registry['sessions'] for ref in (session['summary'],session['evidence'],session['attachment'])]
copied={}
def copy(name,digest,size=None):
    path=source/name
    assert path.resolve().is_relative_to(source) and not path.is_symlink()
    body=path.read_bytes()
    assert hashlib.sha256(body).hexdigest()==digest
    if size is not None: assert len(body)==size
    target=artifacts/name
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    target.write_bytes(body)
    target.chmod(0o400)
    copied[name]={'sha256':digest,'size_bytes':len(body)}
for ref in refs: copy(ref['path'],ref['sha256'],ref['size_bytes'])
for name,digest in registry['source_sha256'].items(): copy(registry['source_directory']+'/'+name,digest)
for directory in sorted((p for p in artifacts.rglob('*') if p.is_dir()),reverse=True): directory.chmod(0o500)
artifacts.chmod(0o500)
(root/'registry.json').write_bytes(raw)
(root/'registry.json').chmod(0o400)
interpreter='/home/DHB/Documents/NANFO/ai-engine/.venv/bin/python'
env={'NANFO_LIVE_MODEL_REGISTRY':str(root/'registry.json'),'NANFO_LIVE_MODEL_REGISTRY_SHA256':hashlib.sha256(raw).hexdigest(),
     'NANFO_MODEL_ROOT':str(artifacts),'NANFO_MODEL_PYTHON':interpreter,'NANFO_LIVE_OBSERVATION_ROOT':str(observations),
     'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1','CUDA_VISIBLE_DEVICES':'',
     'HOME':str(root),'TMPDIR':str(root),'LANG':'C.UTF-8'}
command=[interpreter,'-I','-B',str(snapshot/'backend/scripts/frozen_live_inference.py'),'qualify']
result=subprocess.run(command,env=env,cwd=root,capture_output=True,timeout=150)
(root/'qualify.stdout').write_bytes(result.stdout)
(root/'qualify.stderr').write_bytes(result.stderr)
proof={'exit_code':result.returncode,'command':command,'registry_sha256':env['NANFO_LIVE_MODEL_REGISTRY_SHA256'],
       'registry_bytes_unchanged':True,'registry_expiry_unchanged':registry['expires_at'],'copied_readonly_inputs':copied,
       'runtime':'existing_independent_host_AI_interpreter_not_backend_image','new_lab_or_training':False,
       'fresh_observer_readiness':'unavailable_no_current_feed_installed','native_autonomy':'blocked'}
if result.returncode==0: proof['qualification']=json.loads(result.stdout)
(root/'result.json').write_text(json.dumps(proof,indent=2))
assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==value['sha256'] for name,value in copied.items())
assert all(hashlib.sha256((artifacts/name).read_bytes()).hexdigest()==value['sha256'] for name,value in copied.items())
print(json.dumps({'directory':str(root),'exit_code':result.returncode,'qualification':proof.get('qualification'),
                  'readonly_input_files':len(copied),'observation_ready':False,'autonomy_ready':False}))
