import json
import shutil
import subprocess
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix='nanfo-adr023-snmp-probe-', dir='/tmp/opencode'))
base = 'sha256:71b31676560195b54b5480507c71c857f064ebaa7cb3f0f793e2fcd8080c9e5a'
(root / 'Dockerfile').write_text(f'FROM {base}\nUSER 0:0\nRUN apt-get update && apt-get install -y --no-install-recommends snmpd=5.9.3+dfsg-2+deb12u1 && rm -rf /var/lib/apt/lists/*\nCOPY probe.py /opt/nanfo/probe.py\nUSER 10001:10001\nENTRYPOINT ["python", "/opt/nanfo/probe.py"]\n')
shutil.copyfile('/tmp/opencode/adr023_snmp_probe.py', root / 'probe.py')
(root / 'probe.py').chmod(0o444)
tag = 'nanfo-deploy-adr023-snmp-probe:' + root.name.rsplit('-', 1)[1]
with (root / 'build.log').open('xb') as log:
    subprocess.run(['docker', 'build', '-t', tag, str(root)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
name = root.name
try:
    result = subprocess.run(['docker', 'run', '--name', name, '--rm', '--pull=never', '--network', 'none', '--read-only',
                             '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--pids-limit', '32', '--memory', '256m',
                             '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777', tag], capture_output=True, timeout=60)
    (root / 'result.private.log').write_bytes(result.stdout + result.stderr)
    record = {'exit_code': result.returncode, 'image_id': subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True).strip(),
              'fleet_image': base}
    if result.returncode == 0:
        record['proof'] = json.loads(result.stdout)
    (root / 'result.json').write_text(json.dumps(record, indent=2))
    print(json.dumps({'directory': str(root), **record}))
finally:
    subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)
