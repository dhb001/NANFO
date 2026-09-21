import base64
import hashlib
import uuid
from datetime import UTC, datetime

from app.modules.network.models import CampusModelAssetRecord
from app.modules.network.schemas import UpsertCampusModelAssetRequest

NETWORK_ID = uuid.UUID(int=2301)
WORKSPACE_ID = uuid.UUID(int=2302)
ORG_ID = uuid.UUID(int=2303)
ACTOR_ID = uuid.UUID(int=2304)


def registration():
    return {"version": 1, "translation": {"x": 1, "y": 2, "z": 3},
            "rotation": {"x": 0, "y": 0, "z": 0}, "scale": {"x": 1, "y": 1, "z": 1},
            "target_units": "m", "target_up_axis": "y", "source": "operator-survey"}


def payload(body=b"campus-model", **changes):
    return {"model_file_name": "campus.glb", "model_mime_type": "model/gltf-binary",
            "model_data_base64": base64.b64encode(body).decode(), "model_sha256": hashlib.sha256(body).hexdigest(),
            "model_size_bytes": len(body), **changes}


def request(body=b"campus-model", **changes):
    return UpsertCampusModelAssetRequest.model_validate(payload(body, **changes))


def row(**changes):
    values = request().model_dump(exclude={"replace_existing"})
    values.update(campus_model_asset_id=uuid.uuid4(), network_id=NETWORK_ID, storage_backend="inline",
                  created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    values.update(changes)
    return CampusModelAssetRecord(**values)
