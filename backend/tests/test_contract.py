"""Keep the shared HTTP contract synchronized with the actual FastAPI routes."""

import json

from app.config import PROJECT_ROOT
from app.main import create_app


def test_openapi_snapshot_matches_implemented_routes(settings):
    expected = json.loads((PROJECT_ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    assert create_app(settings).openapi() == expected
