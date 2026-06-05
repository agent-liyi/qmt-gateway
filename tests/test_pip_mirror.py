"""pip 国内源配置测试 (#49)"""

from pathlib import Path
from unittest.mock import patch

from qmt_gateway.services.pip_mirror import (
    DEFAULT_INDEX_URL,
    ensure_pip_conf,
    get_pip_index_url,
)


def test_get_pip_index_url_returns_default():
    with patch("qmt_gateway.services.pip_mirror._find_pip_conf", return_value=None):
        assert get_pip_index_url() == DEFAULT_INDEX_URL


def test_get_pip_index_url_reads_from_conf(tmp_path):
    conf = tmp_path / "pip.conf"
    conf.write_text("[global]\nindex-url = https://mirrors.aliyun.com/pypi/simple\n", encoding="utf-8")

    with patch("qmt_gateway.services.pip_mirror._find_pip_conf", return_value=conf):
        assert get_pip_index_url() == "https://mirrors.aliyun.com/pypi/simple"


def test_ensure_pip_conf_creates_when_missing(tmp_path):
    conf = tmp_path / "pip.conf"

    with patch("qmt_gateway.services.pip_mirror._find_pip_conf", return_value=conf):
        assert ensure_pip_conf() is True
        assert conf.exists()
        content = conf.read_text(encoding="utf-8")
        assert DEFAULT_INDEX_URL in content


def test_ensure_pip_conf_noop_when_exists(tmp_path):
    conf = tmp_path / "pip.conf"
    conf.write_text("[global]\nindex-url = https://example.com\n", encoding="utf-8")

    with patch("qmt_gateway.services.pip_mirror._find_pip_conf", return_value=conf):
        assert ensure_pip_conf() is True
        assert conf.read_text(encoding="utf-8") == "[global]\nindex-url = https://example.com\n"


def test_ensure_pip_conf_returns_false_when_no_venv():
    with patch("qmt_gateway.services.pip_mirror._find_pip_conf", return_value=None):
        assert ensure_pip_conf() is False
