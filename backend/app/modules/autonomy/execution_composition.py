"""Explicit deployment composition. No default installation and no lab launch."""

from dataclasses import dataclass

from app.modules.autonomy.execution import build_execution_providers
from app.modules.autonomy.safety_installation import load_independently_validated_safety
from app.modules.autonomy.safety_provider import CalibratedSafetyProvider
from emulation.actions import Actions
from emulation.autonomous_driver import IsolatedOVSDriver
from emulation.autonomous_ownership import IsolatedLabOwnership


@dataclass
class AutonomousLabProviders:
    safety: CalibratedSafetyProvider
    executor: object
    recovery: object
    ownership: IsolatedLabOwnership

    def close(self):
        """Call only after the receiver task and all device calls have finished."""
        self.ownership.close()


def compose_autonomous_lab(*, sessions, redis, lab, resource_id, results_directory,
                           execution_mode, manual_enabled, experiment_enabled, calibration_config):
    if execution_mode != "emulation":
        raise ValueError("production_autonomous_driver_unavailable")
    installation = load_independently_validated_safety(**calibration_config)
    if str(lab.runId) != installation.data.calibration.run_id:
        raise ValueError("calibration_lab_run_mismatch")
    ownership = IsolatedLabOwnership(lab, resource_id, results_directory=results_directory,
        manual_enabled=manual_enabled, experiment_enabled=experiment_enabled)
    try:
        driver = IsolatedOVSDriver(Actions(lab), resource_id=resource_id, run_id=lab.runId,
                                   ownership_check=ownership.check)
        executor, recovery = build_execution_providers(sessions, redis, installation, driver, resource_id,
                                                       execution_mode=execution_mode)
        return AutonomousLabProviders(CalibratedSafetyProvider(sessions, installation), executor, recovery, ownership)
    except BaseException:
        ownership.close()
        raise
