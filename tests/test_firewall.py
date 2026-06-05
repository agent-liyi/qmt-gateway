"""防火墙规则管理测试 (#49)"""

from unittest.mock import MagicMock, patch

from qmt_gateway.services.firewall import FirewallManager


def test_rule_exists_returns_true():
    mgr = FirewallManager()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Rule Name: QMT Gateway\n"
        )
        assert mgr.rule_exists() is True


def test_rule_exists_returns_false_when_not_found():
    mgr = FirewallManager()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert mgr.rule_exists() is False


def test_rule_exists_returns_false_on_exception():
    mgr = FirewallManager()
    with patch("subprocess.run", side_effect=Exception("fail")):
        assert mgr.rule_exists() is False


def test_add_rule_success():
    mgr = FirewallManager()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert mgr.add_rule(8130) is True
        args = mock_run.call_args[0][0]
        assert "netsh" in args
        assert "localport=8130" in args
        assert "profile=private" in args


def test_add_rule_fails():
    mgr = FirewallManager()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        assert mgr.add_rule(8130) is False


def test_remove_rule_success():
    mgr = FirewallManager()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert mgr.remove_rule() is True
        args = mock_run.call_args[0][0]
        assert "delete" in args


def test_update_port_removes_then_adds():
    mgr = FirewallManager()
    with patch.object(mgr, "rule_exists", return_value=True), \
         patch.object(mgr, "remove_rule", return_value=True) as mock_remove, \
         patch.object(mgr, "add_rule", return_value=True) as mock_add:
        assert mgr.update_port(8131) is True
        mock_remove.assert_called_once()
        mock_add.assert_called_once_with(8131)


def test_update_port_adds_when_no_existing_rule():
    mgr = FirewallManager()
    with patch.object(mgr, "rule_exists", return_value=False), \
         patch.object(mgr, "remove_rule") as mock_remove, \
         patch.object(mgr, "add_rule", return_value=True) as mock_add:
        assert mgr.update_port(8131) is True
        mock_remove.assert_not_called()
        mock_add.assert_called_once_with(8131)
