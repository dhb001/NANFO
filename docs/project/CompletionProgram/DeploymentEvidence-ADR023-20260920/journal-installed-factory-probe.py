"""Offline installed-factory default/partial/production checks; no trust fixture."""
import json
import os
import sys
from app.modules.autonomy.providers import installed_providers
from app.modules.autonomy.execution_client import JournalExecutionClient

assert not hasattr(JournalExecutionClient, 'run')
proofs=[]
for label, values in (
    ('unconfigured', {}),
    ('partial', {'NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256': 'a'*64}),
    ('missing_protected_config', {'NANFO_AUTONOMOUS_PROVIDER_CONFIG': '/missing/provider.json', 'NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256':'a'*64}),
):
    for key in ('NANFO_AUTONOMOUS_PROVIDER_CONFIG', 'NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256'):
        os.environ.pop(key,None)
    os.environ.update(values)
    providers=installed_providers(None,None)
    assert providers.executor.status.status=='unavailable'
    assert providers.safety.status.status==('unavailable' if values else 'uncalibrated')
    assert not hasattr(providers.executor,'run')
    if values:
        assert providers.executor.status.reasons==['autonomous_installation_invalid_or_incompatible']
    proofs.append(label)
print(json.dumps({'passed':len(proofs),'failed':0,'execution_mode':os.environ['EXECUTION_MODE'],
                  'proofs':proofs,'driver_modules_imported':[name for name in ('emulation.autonomous_frr','emulation.autonomous_namespace') if name in sys.modules],
                  'journal_client_has_run':False,'executor_types':[type(providers.executor).__name__]}))
