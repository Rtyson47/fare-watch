"""Shared pytest fixtures. Lives at repo root so `farewatch` imports resolve."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name):
        with open(FIXTURES / name) as f:
            return json.load(f)
    return _load


@pytest.fixture
def sample_config(tmp_path):
    """A writable copy of config.example.yaml, returned as a Path."""
    src = (ROOT / "config.example.yaml").read_text()
    p = tmp_path / "config.yaml"
    p.write_text(src)
    return p


@pytest.fixture
def conn(tmp_path):
    """An initialised, empty SQLite connection on a temp file."""
    from farewatch import db
    return db.connect(str(tmp_path / "fare_watch.db"))
