import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time

os.umask(0o077)
root = Path(tempfile.mkdtemp(prefix='nanfo-adr023-fleet-full-', dir='/tmp/opencode'))
name = root.name
base = 'sha256:1e28594b60848453be3221182c4808a76b186e34e7e71835e6270085138395d6'
(root / 'Dockerfile').write_text(f'FROM {base}\nCOPY probe.py /opt/nanfo/fleet_probe.py\nENTRYPOINT ["python", "/opt/nanfo/fleet_probe.py"]\n')
shutil.copyfile('/tmp/opencode/adr023_fleet_full_probe.py', root / 'probe.py')
(root / 'probe.py').chmod(0o444)
tag = 'nanfo-deploy-adr023-fleet-full:' + name.rsplit('-', 1)[1]
with (root / 'build.log').open('xb') as log:
    subprocess.run(['docker','build','-t',tag,str(root)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
pgpass, redispass = secrets.token_hex(24), secrets.token_hex(24)
env = {'POSTGRES_HOST': 'postgres', 'POSTGRES_DB': 'nanfo', 'POSTGRES_USER': 'postgres', 'POSTGRES_PASSWORD': pgpass,
       'REDIS_HOST': 'redis', 'REDIS_PASSWORD': redispass, 'NEO4J_URI': 'bolt://unused:7687', 'NEO4J_USER': 'unused',
       'NEO4J_PASSWORD': secrets.token_hex(24), 'JWT_SECRET_KEY': secrets.token_hex(32), 'EXECUTION_MODE': 'emulation'}
(root / 'runtime.env').write_text(''.join(f'{k}={v}\n' for k,v in env.items()))
(root / 'postgres.env').write_text(f'POSTGRES_DB=nanfo\nPOSTGRES_PASSWORD={pgpass}\n')
(root / 'redis.conf').write_text(f'bind 0.0.0.0\nprotected-mode yes\nrequirepass {redispass}\nsave ""\nappendonly no\n')
(root / 'redis.conf').chmod(0o644) # Random isolated password; root0700 protects host path.
owned = []
def run(*args, **kw):
    return subprocess.run(args, capture_output=True, check=True, timeout=kw.pop('timeout',60), **kw)
try:
    run('docker','network','create','--internal',name)
    for service, image, extra in (
        ('postgres','sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3',
         ['--tmpfs','/var/lib/postgresql/data:rw,nosuid,nodev,size=256m','--env-file',str(root/'postgres.env')]),
        ('redis','sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb',
         ['--mount',f'type=bind,src={root}/redis.conf,dst=/etc/redis-test.conf,readonly']),
    ):
        container=name+'-'+service
        run('docker','run','-d','--rm','--pull=never','--name',container,'--network',name,'--network-alias',service,
            '--memory','384m',*extra,image,*(['redis-server','/etc/redis-test.conf'] if service=='redis' else []))
        owned.append(container)
    for _ in range(30):
        result=subprocess.run(['docker','exec',name+'-postgres','pg_isready','-U','postgres','-d','nanfo'],capture_output=True,timeout=5)
        if result.returncode==0: break
        time.sleep(1)
    else: raise AssertionError('private PostgreSQL startup deadline')
    container=name+'-worker'
    owned.append(container)
    result=subprocess.run(['docker','run','--rm','--pull=never','--name',container,'--network',name,'--read-only',
        '--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','64','--memory','512m',
        '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777','--env-file',str(root/'runtime.env'),tag],
        capture_output=True,timeout=240)
    (root/'result.private.log').write_bytes(result.stdout+result.stderr)
    record={'exit_code':result.returncode,'fleet_image':'sha256:71b31676560195b54b5480507c71c857f064ebaa7cb3f0f793e2fcd8080c9e5a',
            'acceptance_image':json.loads(run('docker','image','inspect',tag).stdout)[0]['Id']}
    if result.returncode==0: record['proof']=json.loads(result.stdout)
finally:
    for container in reversed(owned): subprocess.run(['docker','rm','-f','-v',container],capture_output=True,timeout=15)
    subprocess.run(['docker','network','rm',name],capture_output=True,timeout=15)
    for secret in ('runtime.env','postgres.env','redis.conf'): (root/secret).unlink(missing_ok=True)
    remaining=subprocess.check_output(['docker','ps','-a','--filter',f'name=^{name}','--format','{{.Names}}'],text=True)
    assert not remaining.strip()
record['cleanup']='owned_containers_network_and_ephemeral_data_removed'
(root/'result.json').write_text(json.dumps(record,indent=2))
print(json.dumps({'directory':str(root),**record}))
