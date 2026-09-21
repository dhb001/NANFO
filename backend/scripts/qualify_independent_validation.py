"""Read-only RF/network evidence verification and exact offline JSON schemas."""

import argparse
import json

from pydantic import ValidationError

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, EvidenceError, StrictEvidence
from app.modules.autonomy.calibration_verification import verify_network_campaign
from app.modules.autonomy.calibration_verification_models import BoundGuarantee, CalibrationInstallation, CalibrationScope, NetworkQualificationConfig, NetworkReading
from app.modules.simulation.qualification_acquisition import LocalAcquisitionRecipe
from app.modules.simulation.qualification_protocol import AcquisitionProtocol, CampaignManifest, InstrumentExport, MeasurementAttestation, RawCapture, import_campaign
from app.modules.simulation.qualification_rf import RFQualificationConfig, RFReading, qualify_rf


class VerificationTrust(StrictEvidence):
    trusted_preregistrations: dict[str, float]
    trusted_attesters: list[str]


SCHEMAS = {
    "protocol": AcquisitionProtocol, "campaign": CampaignManifest, "capture": RawCapture,
    "instrument": InstrumentExport, "attestation": MeasurementAttestation,
    "rf-config": RFQualificationConfig, "rf-reading": RFReading,
    "network-config": NetworkQualificationConfig, "network-reading": NetworkReading,
    "installation": CalibrationInstallation, "scope": CalibrationScope,
    "guarantee": BoundGuarantee, "local-recipe": LocalAcquisitionRecipe, "trust": VerificationTrust,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", choices=SCHEMAS)
    parser.add_argument("--root")
    parser.add_argument("--manifest")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--manifest-size", type=int)
    parser.add_argument("--trust-root", help="Separate protected operator trust root")
    parser.add_argument("--trust", help="Trust receipt filename, never sourced from dossier")
    args = parser.parse_args(argv)
    if args.schema:
        print(json.dumps(SCHEMAS[args.schema].model_json_schema(), sort_keys=True))
        return 0
    if not all((args.root, args.manifest, args.manifest_sha256, args.manifest_size, args.trust_root, args.trust)):
        parser.error("supply root, exact manifest reference and separate trust receipt")
    try:
        trust = VerificationTrust.model_validate(ArtifactStore(args.trust_root).document(args.trust))
        campaign = import_campaign(ArtifactStore(args.root), ArtifactRef(
            path=args.manifest, sha256=args.manifest_sha256, size_bytes=args.manifest_size,
        ), trusted_preregistrations=trust.trusted_preregistrations,
            trusted_attesters=set(trust.trusted_attesters))
        result = qualify_rf(campaign) if campaign.protocol.domain == "rf" else verify_network_campaign(campaign)
    except (EvidenceError, ValidationError, OverflowError) as exc:
        result = {"empirical_acceptance_passed": False, "physical_qualified": False,
                  "reason": str(exc) if isinstance(exc, EvidenceError) else "invalid_evidence_schema"}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["empirical_acceptance_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
