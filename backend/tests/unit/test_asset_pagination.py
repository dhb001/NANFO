from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.network.repository import CampusModelAssetRepository
from tests.asset_support import NETWORK_ID


async def test_metadata_projection_scope_order_and_bound():
    db = AsyncMock()
    db.scalar.return_value = 42
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    db.execute.return_value = result
    assert await CampusModelAssetRepository(db).list_metadata_for_network(NETWORK_ID, page=3, page_size=20) == ([], 42)
    count = db.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    query = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    for statement in (count, query):
        assert "campus_model_assets.network_id =" in str(statement)
        assert "campus_model_assets.deleted_at IS NULL" in str(statement)
        assert NETWORK_ID in statement.params.values()
        assert "model_data_base64" not in str(statement)
    assert "ORDER BY campus_model_assets.created_at ASC, campus_model_assets.campus_model_asset_id ASC" in str(query)
    assert query.params["param_1"] == 20 and query.params["param_2"] == 40


@pytest.mark.parametrize("page,size", [(0, 20), (1, 0), (1, 101)])
async def test_internal_metadata_bounds(page, size):
    db = AsyncMock()
    with pytest.raises(ValueError):
        await CampusModelAssetRepository(db).list_metadata_for_network(NETWORK_ID, page=page, page_size=size)
    db.execute.assert_not_awaited()
    db.scalar.assert_not_awaited()
