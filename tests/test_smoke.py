"""Basic smoke tests for the standalone qmt-gateway package."""

from qmt_gateway import __version__
from qmt_gateway.app import app


def test_package_version_present():
    assert __version__ == "0.1.0"


def test_app_importable():
    assert app is not None
