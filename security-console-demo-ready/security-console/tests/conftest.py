import os
import pytest

from client import ControlLayerClient


@pytest.fixture(scope="session")
def control():
    return ControlLayerClient(os.getenv("CONTROL_LAYER_URL", "http://127.0.0.1:9000"))
