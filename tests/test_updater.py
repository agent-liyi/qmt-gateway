"""版本检查与内核更新测试 (#49)"""

import json
from unittest.mock import MagicMock, patch

from qmt_gateway.services.updater import (
    UpdateInfo,
    UpdateResult,
    check_update,
    create_update_task,
    get_current_version,
    get_update_task,
    rollback,
)


def test_get_current_version_returns_string():
    ver = get_current_version()
    assert isinstance(ver, str)
    assert len(ver) > 0


def test_check_update_no_update_available():
    with patch("qmt_gateway.services.updater.get_current_version", return_value="1.0.0"), \
         patch("qmt_gateway.services.updater.get_latest_version", return_value={
             "version": "1.0.0", "release_url": ""
         }):
        info = check_update()
        assert info.has_update is False
        assert info.current_version == "1.0.0"
        assert info.latest_version == "1.0.0"


def test_check_update_has_update():
    with patch("qmt_gateway.services.updater.get_current_version", return_value="0.1.0"), \
         patch("qmt_gateway.services.updater.get_latest_version", return_value={
             "version": "0.2.0", "release_url": "https://example.com"
         }):
        info = check_update()
        assert info.has_update is True
        assert info.current_version == "0.1.0"
        assert info.latest_version == "0.2.0"


def test_check_update_pypi_error():
    with patch("qmt_gateway.services.updater.get_current_version", return_value="0.1.0"), \
         patch("qmt_gateway.services.updater.get_latest_version", return_value={
             "error": "network error"
         }):
        info = check_update()
        assert info.has_update is False
        assert info.error == "network error"


def test_create_and_get_update_task():
    task_id = create_update_task()
    task = get_update_task(task_id)
    assert task is not None
    assert task.task_id == task_id
    assert task.status == "pending"


def test_get_update_task_nonexistent():
    assert get_update_task("nonexistent") is None


def test_rollback_no_backup_available():
    with patch("qmt_gateway.services.updater.get_installed_versions", return_value=[]), \
         patch("qmt_gateway.services.updater.get_current_version", return_value="0.1.0"):
        result = rollback()
        assert result.success is False
        assert "没有可用的备份版本" in result.error


def test_rollback_to_specific_version():
    with patch("qmt_gateway.services.updater._restore_backup", return_value=True), \
         patch("qmt_gateway.services.updater.get_current_version", return_value="0.2.0"):
        result = rollback("0.1.0")
        assert result.success is True
        assert result.old_version == "0.2.0"
        assert result.new_version == "0.1.0"


def test_rollback_to_specific_version_fails():
    with patch("qmt_gateway.services.updater._restore_backup", return_value=False), \
         patch("qmt_gateway.services.updater.get_current_version", return_value="0.2.0"):
        result = rollback("0.1.0")
        assert result.success is False
