"""开机自启管理测试 (#49)"""

from unittest.mock import MagicMock, patch

from qmt_gateway.services.autostart import AutoStartManager


def test_is_enabled_returns_true_when_task_exists():
    mgr = AutoStartManager()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert mgr.is_enabled() is True


def test_is_enabled_returns_false_when_task_missing():
    mgr = AutoStartManager()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert mgr.is_enabled() is False


def test_is_enabled_returns_false_on_exception():
    mgr = AutoStartManager()
    with patch("subprocess.run", side_effect=Exception("fail")):
        assert mgr.is_enabled() is False


def test_enable_success():
    mgr = AutoStartManager(script_path="C:\\test\\start-silent.vbs")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert mgr.enable() is True
        args = mock_run.call_args[0][0]
        assert "schtasks" in args
        assert "/create" in args
        assert "QMT Gateway" in args


def test_enable_fails_without_script_path():
    mgr = AutoStartManager()
    assert mgr.enable() is False


def test_enable_fails_on_subprocess_error():
    mgr = AutoStartManager(script_path="C:\\test\\start-silent.vbs")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        assert mgr.enable() is False


def test_disable_success():
    mgr = AutoStartManager()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert mgr.disable() is True
        args = mock_run.call_args[0][0]
        assert "schtasks" in args
        assert "/delete" in args


def test_disable_fails_on_subprocess_error():
    mgr = AutoStartManager()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        assert mgr.disable() is False
