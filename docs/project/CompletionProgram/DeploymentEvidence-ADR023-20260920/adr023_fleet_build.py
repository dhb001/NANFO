import json
import subprocess
import sys
import tempfile
from pathlib import Path

snapshot = Path(sys.argv[1])
directory = Path(tempfile.mkdtemp(prefix='nanfo-adr023-fleet-build-', dir='/tmp/opencode'))
tag = 'nanfo-deploy-adr023-fleet:' + directory.name.rsplit('-', 1)[1]
command = ['docker', 'build', '--target', 'with-fleet', '-f', 'deploy/Dockerfile.backend', '-t', tag, '.']
with (directory / 'build.log').open('xb') as log:
    result = subprocess.run(command, cwd=snapshot, stdout=log, stderr=subprocess.STDOUT, timeout=900)
record = {'snapshot': str(snapshot), 'tag': tag, 'exit_code': result.returncode, 'command': command}
if result.returncode == 0:
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag]))[0]
    record['image_id'] = image['Id']
    record['packages'] = subprocess.check_output([
        'docker', 'run', '--rm', '--pull=never', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true', '--entrypoint', 'dpkg-query', image['Id'],
        '-W', '-f=${Package} ${Version}\n', 'snmp', 'libsnmp40', 'libsnmp-base'], text=True)
(directory / 'result.json').write_text(json.dumps(record, indent=2))
print(json.dumps({'directory': str(directory), **record}))
