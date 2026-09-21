"""Freeze admitted source, launch bounded isolated verifier, preserve private logs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path('/home/DHB/Documents/NANFO')


def freeze():
    deny = {'node_modules', 'dist', 'artifacts', 'output', 'results', 'commands', 'secrets',
            'keys', '__pycache__', 'venv', '.venv', 'test-results', 'playwright-report'}
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--',
                                     'deploy', 'backend', 'frontend', 'emulation', 'ai-engine'], cwd=ROOT).decode().split('\0')
    names = sorted({p for p in paths if p and not p.startswith('deploy/state/') and not any(part in deny for part in Path(p).parts)
                    and not Path(p).name.startswith('.env') and not p.endswith(('.key', '.pem', '.pyc'))
                    and (ROOT / p).is_file() and not (ROOT / p).is_symlink()})
    data = {name: (ROOT / name).read_bytes() for name in names}
    assert all((ROOT / name).read_bytes() == raw for name, raw in data.items())
    snapshot = Path(tempfile.mkdtemp(prefix='nanfo-adr023-frozen-', dir='/tmp/opencode'))
    for name, raw in data.items():
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o444)
    for path in snapshot.rglob('*'):
        if path.is_dir():
            path.chmod(0o755)
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()}
    (snapshot / 'source-snapshot.json').write_text(json.dumps(hashes, sort_keys=True, indent=2))
    subprocess.run(['git', 'init', '--quiet', str(snapshot)], check=True)
    subprocess.run(['git', 'add', '--', *names], cwd=snapshot, check=True)
    print(json.dumps({'snapshot': str(snapshot), 'files': len(names), 'bytes': sum(map(len, data.values()))}))


def launch(snapshot, mode, extra):
    directory = Path(tempfile.mkdtemp(prefix='nanfo-adr023-' + mode + '-', dir='/tmp/opencode'))
    command = [sys.executable, 'deploy/verify.py', '--live', '--agents-idle', '--work-root', '/tmp/opencode']
    if mode == 'distributed':
        command.append('--distributed')
    command.extend(extra)
    with (directory / 'campaign.log').open('xb') as log:
        process = subprocess.Popen(['timeout', '--signal=TERM', '--kill-after=150', '2400', *command],
                                   cwd=snapshot, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (directory / 'launch.json').write_text(json.dumps({'pid': process.pid, 'snapshot': snapshot, 'command': command}))
    print(json.dumps({'pid': process.pid, 'log': str(directory / 'campaign.log'), 'launch': str(directory)}))


if __name__ == '__main__':
    os.umask(0o077)
    if sys.argv[1] == 'freeze':
        freeze()
    else:
        launch(sys.argv[2], sys.argv[1], sys.argv[3:])
