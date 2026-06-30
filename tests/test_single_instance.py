"""单实例锁测试"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from qmt_gateway.__main__ import (
    _acquire_single_instance_lock,
    _is_pid_alive,
    _pid_belongs_to_gateway,
    _release_single_instance_lock,
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path


def _own_pid() -> int:
    return os.getpid()


def test_acquire_lock_first_time_succeeds(home: Path):
    assert _acquire_single_instance_lock(home) is True
    lock = home / ".lock"
    assert lock.exists()
    payload = json.loads(lock.read_text(encoding="utf-8"))
    assert payload["pid"] == _own_pid()
    assert payload["argv_substring"] == "qmt_gateway"
    assert "started_at" in payload


def test_acquire_lock_twice_with_live_pid_fails(home: Path):
    """PID 活着 + 命令行含 qmt_gateway——视为活动锁，第二次拿不到。"""
    assert _acquire_single_instance_lock(home) is True
    with patch("qmt_gateway.__main__._pid_belongs_to_gateway", return_value=True):
        assert _acquire_single_instance_lock(home) is False
    # 第一次的锁还在，没被覆盖
    payload = json.loads((home / ".lock").read_text(encoding="utf-8"))
    assert payload["pid"] == _own_pid()


def test_acquire_lock_with_stale_pid_cleans_up_and_succeeds(home: Path):
    """PID 已死 / 命令行不再是 qmt_gateway——清理旧锁，重新占。"""
    # 模拟上次进程崩溃，留下一个死 PID 的锁（裸数字格式，旧版本遗留）
    (home / ".lock").write_text("999999", encoding="utf-8")
    with patch("qmt_gateway.__main__._pid_belongs_to_gateway", return_value=False):
        assert _acquire_single_instance_lock(home) is True
    payload = json.loads((home / ".lock").read_text(encoding="utf-8"))
    assert payload["pid"] == _own_pid()


def test_acquire_lock_with_polluted_pid_cleans_up_and_succeeds(home: Path):
    """PID 复用到另一个进程（PID 还活着但不是我们）——按 stale 处理。

    复现现场：2026-06-30 用户点托盘"停止" → gateway 死 → .lock 没及时清理
    → 同号 PID 被 smartscreen.exe 复用 → 新 gateway 启动时被 _is_pid_alive
    误判为"另一个实例还在跑" → 退出码 2 → 用户从开始菜单启动无效。
    """
    # 模拟旧 lock 指向一个"还活着但不是我们"的进程
    polluted_pid = 99999
    (home / ".lock").write_text(
        json.dumps({"pid": polluted_pid, "argv_substring": "qmt_gateway"}),
        encoding="utf-8",
    )
    # _pid_belongs_to_gateway 探测后发现命令行不包含 qmt_gateway（已经被其他进程占）
    with patch("qmt_gateway.__main__._pid_belongs_to_gateway", return_value=False):
        assert _acquire_single_instance_lock(home) is True
    payload = json.loads((home / ".lock").read_text(encoding="utf-8"))
    assert payload["pid"] == _own_pid()


def test_release_lock_removes_own_lock(home: Path):
    assert _acquire_single_instance_lock(home) is True
    _release_single_instance_lock(home)
    assert not (home / ".lock").exists()


def test_release_lock_does_not_remove_foreign_lock(home: Path):
    # 别人刚拿到的锁（不同 PID），不能误删
    other_pid = 123456
    (home / ".lock").write_text(
        json.dumps({"pid": other_pid, "argv_substring": "qmt_gateway"}),
        encoding="utf-8",
    )
    _release_single_instance_lock(home)
    payload = json.loads((home / ".lock").read_text(encoding="utf-8"))
    assert payload["pid"] == other_pid


def test_acquire_lock_after_release_succeeds(home: Path):
    assert _acquire_single_instance_lock(home) is True
    _release_single_instance_lock(home)
    assert _acquire_single_instance_lock(home) is True


def test_acquire_lock_handles_corrupt_lock_file(home: Path):
    """锁文件内容损坏——按 stale 处理，删掉重建。"""
    (home / ".lock").write_text("not even json or a pid", encoding="utf-8")
    assert _acquire_single_instance_lock(home) is True
    payload = json.loads((home / ".lock").read_text(encoding="utf-8"))
    assert payload["pid"] == _own_pid()


def test_is_pid_alive_returns_false_for_zero():
    assert _is_pid_alive(0) is False
    assert _is_pid_alive(-1) is False


def test_is_pid_alive_returns_true_for_self():
    assert _is_pid_alive(os.getpid()) is True


def test_pid_belongs_to_gateway_returns_false_for_zero():
    assert _pid_belongs_to_gateway(0) is False


def test_pid_belongs_to_gateway_returns_false_for_dead_pid():
    assert _pid_belongs_to_gateway(999_999) is False
