"""Root test fixtures: compiles stay in the session temp directory; CardDemo installs into a fresh system directory."""

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.carddemo_system import installed_carddemo


@pytest.fixture(autouse=True, scope="session")
def _compiles_stay_in_the_session_temp_dir(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    tempfile.tempdir = str(tmp_path_factory.mktemp("compile"))
    yield
    tempfile.tempdir = None


@pytest.fixture
def carddemo_system(tmp_path: Path) -> Path:
    return installed_carddemo(tmp_path)
