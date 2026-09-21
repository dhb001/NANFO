"""Installed-image negative trust checks; no calibration/receiver activation."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile

from app.modules.autonomy.providers import installed_providers
from app.modules.autonomy.execution_client import JournalExecutionClient
from app.modules.autonomy.artifact_io import ArtifactRef
from app.modules.autonomy.health_secret import read_health_secret

assert not hasattr(JournalExecutionClient, 'run')
proofs=[]
for label, values in (
    ('unconfigured', {}),
    ('partial', {'NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256': 'a'*64}),
    ('missing_protected_config', {'NANFO_AUTONOMOUS_PROVIDER_CONFIG': '/missing/provider.json',
                                  'NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256':'a'*64}),
):
    for key in ('NANFO_AUTONOMOUS_PROVIDER_CONFIG','NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256'):
        os.environ.pop(key,None)
    os.environ.update(values)
    providers=installed_providers(None,None)
    assert providers.executor.status.status=='unavailable'
    assert providers.safety.status.status==('unavailable' if values else 'uncalibrated')
    assert not hasattr(providers.executor,'run') and not hasattr(providers.executor,'driver')
    if values:
        assert providers.executor.status.reasons==['autonomous_installation_invalid_or_incompatible']
    proofs.append(label)
for name in ('emulation.autonomous_frr','emulation.autonomous_namespace','emulation.autonomous_driver'):
    assert name not in sys.modules, name
proofs.append('privileged_driver_import_separation')
with tempfile.TemporaryDirectory(prefix='health-secret-smoke-') as directory:
    root=Path(directory)
    root.chmod(0o700)
    key=secrets.token_bytes(32)
    path=root/'receiver.key'
    path.write_bytes(key)
    path.chmod(0o600)
    reference=ArtifactRef(path='receiver.key',sha256=hashlib.sha256(key).hexdigest(),size_bytes=len(key))
    assert read_health_secret(root,reference)==key
    proofs.append('private_0600_key_read')
    for mode in (0o644,0o640,0o400):
        path.chmod(mode)
        try:
            read_health_secret(root,reference)
        except ValueError as exc:
            assert str(exc)=='health_secret_requires_private_0600'
        else:
            raise AssertionError('non-0600 key admitted')
        proofs.append('key_mode_'+oct(mode)+'_rejected')
    path.chmod(0o600)
    os.link(path,root/'hardlink')
    try:
        read_health_secret(root,reference)
    except ValueError:
        pass
    else:
        raise AssertionError('hardlinked key admitted')
    proofs.append('hardlinked_key_rejected')
    (root/'hardlink').unlink()
    path.write_bytes(secrets.token_bytes(32))
    try:
        read_health_secret(root,reference)
    except ValueError as exc:
        assert str(exc)=='health_secret_changed_or_hash_mismatch'
    else:
        raise AssertionError('key digest mismatch admitted')
    proofs.append('key_digest_mismatch_rejected')
print(json.dumps({'passed':len(proofs),'failed':0,'proofs':proofs,
                  'execution_mode':os.environ['EXECUTION_MODE'],'driver_imported':False,
                  'authentic_installation_loaded':False,'receiver_started':False}))
