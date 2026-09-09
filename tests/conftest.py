import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def sample_records() -> list[dict]:
    return json.loads((FIXTURES / "sample_symbols.json").read_text(encoding="utf-8"))


@pytest.fixture()
def sample_records_path() -> Path:
    return FIXTURES / "sample_symbols.json"
