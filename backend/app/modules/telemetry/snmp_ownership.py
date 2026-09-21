"""Measured collector composition using existing Identity/Network public services."""

from __future__ import annotations

from ipaddress import ip_address
from pathlib import Path

from app.modules.identity.service import AuthService
from app.modules.network.service import DeviceService, NetworkService
from app.modules.telemetry.snmp_config import SNMPBinding, SNMPError, load_protected_json


async def validate_owner_scope(binding: SNMPBinding, *, publish: bool, identity: AuthService,
                               network: NetworkService, devices: DeviceService) -> None:
    """No cross-module repositories/SQL; require active inventory and exact IP."""
    profile = await identity.get_profile(str(binding.actor_user_id))
    required = {"read:telemetry", "read:topology"}
    if publish:
        required.add("write:config")
    if not required.issubset(profile.permissions):
        raise SNMPError("collector_permission_denied")
    await network.assert_network_workspace_access(
        network_id=binding.network_id, requested_workspace_id=binding.workspace_id,
        actor_user_id=str(binding.actor_user_id), claim_org_id=binding.org_id, require_write=publish,
    )
    scope = await network.assert_device_workspace_access(
        device_id=binding.device_id, requested_workspace_id=binding.workspace_id,
        actor_user_id=str(binding.actor_user_id), claim_org_id=binding.org_id,
    )
    if scope != (binding.network_id, binding.workspace_id):
        raise SNMPError("device_scope_mismatch")
    # Existing owner API has no get-device contract. Bound pagination and fail
    # closed when the target is beyond the supported 6,400-device inventory.
    for page in range(1, 33):
        response = await devices.list_devices(
            network_id=binding.network_id, actor_user_id=str(binding.actor_user_id), page=page,
            page_size=200, requested_workspace_id=binding.workspace_id, claim_org_id=binding.org_id,
        )
        for device in response.items:
            if device.device_id == binding.device_id:
                try:
                    matches = device.ip_address is not None and ip_address(device.ip_address) == binding.target
                except ValueError:
                    matches = False
                if device.status != "active" or device.network_id != binding.network_id or not matches:
                    raise SNMPError("device_inventory_binding_mismatch")
                return
        if page * 200 >= response.total or not response.items:
            break
    raise SNMPError("device_missing_or_inventory_limit")


class SNMPOwnerBoundary:
    def __init__(self, *, binding_path: Path, session_factory, redis):
        self.binding_path = binding_path
        self.session_factory = session_factory
        self.redis = redis

    async def authorize(self, binding: SNMPBinding, publish: bool) -> None:
        if load_protected_json(self.binding_path, SNMPBinding) != binding:
            raise SNMPError("binding_changed_restart_required")
        try:
            async with self.session_factory() as db:
                await validate_owner_scope(
                    binding, publish=publish, identity=AuthService(db, self.redis),
                    network=NetworkService(db, self.redis), devices=DeviceService(db, self.redis),
                )
        except SNMPError:
            raise
        except Exception:
            raise SNMPError("owner_authorization_failed_or_unavailable") from None
