import asyncio
import json
import os
import secrets
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.modules.telemetry.snmp_config import SNMPBinding
from app.modules.telemetry.snmp_transport import NetSNMPTransport


async def main():
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='snmp-acceptance-') as temporary:
        root = Path(temporary)
        for name in ('home', 'state', 'config'):
            (root / name).mkdir(mode=0o700)
        credential = {'username': 'accept' + secrets.token_hex(4), 'auth_passphrase': secrets.token_hex(16),
                      'priv_passphrase': secrets.token_hex(16)}
        credentials = root / 'credentials.json'
        credentials.write_text(json.dumps(credential))
        credentials.chmod(0o600)
        config = root / 'config/snmpd.conf'
        config.write_text(
            'agentaddress udp:127.0.0.1:1161\nsysName isolated-adr023\n'
            f"createUser {credential['username']} SHA-256 {credential['auth_passphrase']} AES {credential['priv_passphrase']}\n"
            'view measured included .1.3.6.1.2.1.1\nview measured included .1.3.6.1.2.1.2\n'
            'view measured included .1.3.6.1.2.1.31\nview measured included .1.3.6.1.6.3.10.2.1.2\n'
            f"rouser {credential['username']} priv -V measured\n")
        config.chmod(0o600)
        agent = subprocess.Popen(['/usr/sbin/snmpd', '-f', '-C', '-c', str(config), '-p', str(root / 'snmpd.pid'), '-Ln'],
                                 env={'HOME': str(root / 'home'), 'SNMPCONFPATH': str(root / 'config'),
                                      'SNMP_PERSISTENT_DIR': str(root / 'state'), 'MIBS': '', 'LC_ALL': 'C'},
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            binding = SNMPBinding.model_validate_json(json.dumps({
                'version': 1, **{key: str(uuid.uuid4()) for key in ('org_id','workspace_id','network_id','device_id','actor_user_id')},
                'target': '127.0.0.1', 'port': 1161, 'sys_name': 'isolated-adr023',
                'interfaces': [{'if_index': 1, 'if_name': 'lo'}], 'execution_mode': 'emulation', 'environment': 'emulation'}))
            transport = NetSNMPTransport(credentials_path=credentials)
            first = None
            for _ in range(20):
                assert agent.poll() is None
                try:
                    first = await transport.get(binding, binding.interfaces[0])
                    break
                except ValueError:
                    await asyncio.sleep(.2)
            assert first is not None
            await asyncio.sleep(1.1)
            second = await transport.get(binding, binding.interfaces[0])
            assert second.uptime > first.uptime and second.rx >= first.rx and second.tx >= first.tx
            print(json.dumps({'status': 'passed', 'sha256_aes': True, 'reads': 2,
                              'uptime_advanced': True, 'counters_monotonic': True,
                              'isolated_loopback': True, 'measured_provenance': 'private_snmpd_loopback_not_physical'}))
        finally:
            agent.terminate()
            try:
                agent.wait(5)
            except subprocess.TimeoutExpired:
                agent.kill()
                agent.wait(5)

asyncio.run(main())
