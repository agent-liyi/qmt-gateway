"""单实例锁测试"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from qmt_gateway.__main__ import (
    _acquire_single_instance_lock,
    _is_pid_alive,
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
    assert lock.read_text(encoding="utf-8").strip() == str(_own_pid())


def test_acquire_lock_twice_with_live_pid_fails(home: Path):
    assert _acquire_single_instance_lock(home) is True
    with patch("qmt_gateway.__main__._is_pid_alive", return_value=True):
        assert _acquire_single_instance_lock(home) is False
    # 第一次的锁还在，没被覆盖
    assert (home / ".lock").read_text(encoding="utf-8").strip() == str(_own_pid())


def test_acquire_lock_with_stale_pid_cleans_up_and_succeeds(home: Path):
    # 模拟上次进程崩溃，留下一个死 PID 的锁
    (home / ".lock").write_text("999999", encoding="utf-8")
    with patch("qmt_gateway.__main__._is_pid_alive", return_value=False):
        assert _acquire_single_instance_lock(home) is True
    assert (home / ".lock").read_text(encoding="utf-8").strip() == str(_own_pid())


def test_release_lock_removes_own_lock(home: Path):
    assert _acquire_single_instance_lock(home) is True
    _release_single_instance_lock(home)
    assert not (home / ".lock").exists()


def test_release_lock_does_not_remove_foreign_lock(home: Path):
    # 别人刚拿到的锁（不同 PID），不能误删
    (home / ".lock").write_text("123456", encoding="utf-8")
    _release_single_instance_lock(home)
    assert (home / ".lock").read_text(encoding="utf-8").strip() == "123456"


def test_acquire_lock_after_release_succeeds(home: Path):
    assert _acquire_single_instance_lock(home) is True
    _release_single_instance_lock(home)
    assert _acquire_single_instance_lock(home) is True


def test_is_pid_alive_returns_false_for_zero():
    assert _is_pid_alive(0) is False
    assert _is_pid_alive(-1) is False


def test_is_pid_alive_returns_true_for_self():
    assert _is_pid_alive(os.getpid()) is True
