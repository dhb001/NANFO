import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

snapshot=Path('/tmp/opencode/nanfo-adr023-frozen-0bco__84')
fleet='sha256:13be46a557ecb7ea22d6d7f0de2e0792b68b44db3021cf1df99ee4971d509702'
root=Path(tempfile.mkdtemp(prefix='nanfo-adr023-journal-probe-',dir='/tmp/opencode'))
hashes=json.loads((snapshot/'source-snapshot.json').read_bytes())
expected={'/opt/nanfo/'+name:digest for name,digest in hashes.items() if name.endswith('.py')
          and name.startswith(('backend/app/','backend/scripts/','backend/alembic/','deploy/','emulation/'))
          and 'tests' not in Path(name).parts and not Path(name).name.startswith('test_') and name!='deploy/verify.py'}
output=subprocess.check_output(['docker','run','--rm','--pull=never','-i','--network','none','--read-only','--cap-drop','ALL',
    '--entrypoint','python',fleet,'-c',"import hashlib,json,sys;from pathlib import Path;e=json.load(sys.stdin);bad=[p for p,h in e.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];print(json.dumps({'files':len(e),'matched':not bad}));sys.exit(bool(bad))"],
    input=json.dumps(expected).encode(),timeout=60)
result={'fleet_image':fleet,'parity':json.loads(output),'factory_checks':[]}
for mode in ('production','emulation'):
    env={'POSTGRES_HOST':'unavailable','POSTGRES_DB':'nanfo','POSTGRES_USER':'unused','POSTGRES_PASSWORD':'not-a-real-credential',
         'REDIS_HOST':'unavailable','REDIS_PASSWORD':'not-a-real-credential','NEO4J_URI':'bolt://unavailable:7687',
         'NEO4J_USER':'unused','NEO4J_PASSWORD':'not-a-real-credential','JWT_SECRET_KEY':'unused-test-value-'*3,'EXECUTION_MODE':mode}
    command=['docker','run','--rm','--pull=never','-i','--network','none','--read-only','--cap-drop','ALL']
    for key,value in env.items(): command+=['-e',key+'='+value]
    command+=['--entrypoint','python',fleet,'-']
    output=subprocess.check_output(command,input=Path('/tmp/opencode/adr023_journal_probe.py').read_bytes(),timeout=60)
    result['factory_checks'].append(json.loads(output))
(root/'result.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'directory':str(root),**result}))
