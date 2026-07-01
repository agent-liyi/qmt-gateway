"""托盘模块单元测试。

聚焦于非 GUI 部分：
- 读 .port / .lock 工具函数
- _kill_gateway 的回退逻辑
- _wait_for_port_free 的边界

pystray 的 win32 消息循环依赖交互式桌面，CI 不能跑；这部分留
手测 / 单独 issue 跟踪。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from qmt_gateway.tray import (
    _kill_gateway,
    _read_pid,
    _read_port,
    _restart_gateway,
    _spawn_gateway,
    _start_gateway,
    _wait_for_port_free,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("QMT_GATEWAY_HOME", str(tmp_path))
    return tmp_path


# ---------- _read_port ----------

def test_read_port_returns_8130_when_no_file(home: Path):
    assert _read_port() == 8130


def test_read_port_reads_value(home: Path):
    (home / ".port").write_text("8131\n", encoding="utf-8")
    assert _read_port() == 8131


def test_read_port_handles_invalid_content(home: Path):
    (home / ".port").write_text("not a number\n", encoding="utf-8")
    assert _read_port() == 8130


def test_read_port_handles_trailing_whitespace(home: Path):
    (home / ".port").write_text("  8135  \n", encoding="utf-8")
    # strip() should handle this
    assert _read_port() == 8135


# ---------- _read_pid ----------

def test_read_pid_returns_none_when_no_lock(home: Path):
    assert _read_pid() is None


def test_read_pid_reads_value(home: Path):
    (home / ".lock").write_text("12345\n", encoding="utf-8")
    assert _read_pid() == 12345


def test_read_pid_reads_json_format(home: Path):
    """新格式：JSON 负载，含 pid / started_at / argv_substring。"""
    payload = {"pid": 12345, "started_at": 1234567890.0, "argv_substring": "qmt_gateway"}
    (home / ".lock").write_text(json.dumps(payload), encoding="utf-8")
    assert _read_pid() == 12345


def test_read_pid_handles_invalid_content(home: Path):
    (home / ".lock").write_text("garbage\n", encoding="utf-8")
    assert _read_pid() is None


def test_read_pid_handles_json_without_pid(home: Path):
    """锁文件是 JSON 但没有 pid 字段——按无效处理。"""
    (home / ".lock").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    assert _read_pid() is None


# ---------- _wait_for_port_free ----------

def test_wait_for_port_free_returns_true_for_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # 端口已经被释放
    assert _wait_for_port_free(port, timeout=1.0) is True


def test_wait_for_port_free_returns_false_when_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            assert _wait_for_port_free(port, timeout=0.5) is False
        finally:
            s.close()


# ---------- _kill_gateway ----------

def test_kill_gateway_no_lock_returns_false(home: Path):
    assert _kill_gateway() is False


def test_kill_gateway_calls_taskkill_without_T(home: Path):
    """taskkill 必须 /F /PID，不能带 /T——/T 会把托盘一起杀掉（见 tray.py）。"""
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch("qmt_gateway.tray.subprocess.run") as mock_run, \
         patch("qmt_gateway.tray._is_pid_alive_windows", return_value=True):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        assert _kill_gateway() is True
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert "taskkill" in cmd
        assert "/F" in cmd
        assert "/PID" in cmd
        assert "/T" not in cmd, (
            "_kill_gateway must NOT use /T (would kill the tray too)"
        )
        assert "99999" in cmd


def test_kill_gateway_handles_nonzero_returncode_when_pid_still_alive(home: Path):
    """taskkill 返回非 0 但 PID 还活着——真的杀不掉，返回 False。"""
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch("qmt_gateway.tray.subprocess.run") as mock_run, \
         patch("qmt_gateway.tray._is_pid_alive_windows", return_value=True):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="not found", stderr=""
        )
        assert _kill_gateway() is False


def test_kill_gateway_succeeds_when_taskkill_fails_but_pid_is_dead(home: Path):
    """taskkill 报"找不到进程"但我们探测到 PID 已死——

    这是 stale lock 场景（用户点"重启"但 gateway 已被外部 kill），
    _kill_gateway 应该认这个状态为"成功"——调用方接下来可以 spawn 新 gateway。
    """
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch("qmt_gateway.tray.subprocess.run") as mock_run, \
         patch("qmt_gateway.tray._is_pid_alive_windows", return_value=False), \
         patch("qmt_gateway.tray._clear_stale_lock") as mock_clear:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="process not found", stderr=""
        )
        assert _kill_gateway() is True
        mock_clear.assert_called_once()


def test_kill_gateway_handles_timeout(home: Path):
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch(
        "qmt_gateway.tray.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="taskkill", timeout=5),
    ):
        assert _kill_gateway() is False


def test_kill_gateway_handles_missing_taskkill(home: Path):
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch(
        "qmt_gateway.tray.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        assert _kill_gateway() is False


# ---------- _restart_gateway / _start_gateway ----------
#
# 用户场景：托盘点"停止" → gateway 被 taskkill /F /PID 杀掉，.lock 残留
# 指向死 PID，atexit 没机会跑。再点"启动"或"重启"必须能从这种状态恢复。
# 之前的 bug 是 _restart_gateway 在 _kill_gateway() 返回 False 时短路掉了
# _spawn_gateway()——结果什么也没发生。新实现加了 try/except + 显式
# "pid 为 None 直接 spawn"分支。

def test_restart_gateway_with_no_running_pid_calls_spawn(home: Path):
    """停止后场景：.lock 不存在（atexit 已删）→ 直接 spawn，不调 kill。"""
    assert _read_pid() is None
    with patch("qmt_gateway.tray._spawn_gateway") as mock_spawn:
        _restart_gateway(None, None)  # type: ignore[arg-type]
        mock_spawn.assert_called_once()


def test_restart_gateway_clears_stale_lock_then_kills_then_spawns(home: Path):
    """.lock 指向死 PID → 先清过期锁，然后走 kill-and-spawn 路径。"""
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch("qmt_gateway.tray._is_pid_alive_windows", return_value=False), \
         patch("qmt_gateway.tray._clear_stale_lock") as mock_clear, \
         patch("qmt_gateway.tray._kill_gateway", return_value=True), \
         patch("qmt_gateway.tray._wait_for_port_free", return_value=True), \
         patch("qmt_gateway.tray._spawn_gateway") as mock_spawn:
        _restart_gateway(None, None)  # type: ignore[arg-type]
        mock_clear.assert_called_once()
        mock_spawn.assert_called_once()


def test_start_gateway_with_no_pid_calls_spawn(home: Path):
    """停止后场景（.lock 已被 atexit 删）→ 直接 spawn。"""
    assert _read_pid() is None
    with patch("qmt_gateway.tray._clear_stale_lock") as mock_clear, \
         patch("qmt_gateway.tray._spawn_gateway") as mock_spawn:
        _start_gateway(None, None)  # type: ignore[arg-type]
        mock_spawn.assert_called_once()


def test_start_gateway_when_already_running_opens_browser(home: Path):
    """gateway 已在跑 → 只打开浏览器，不重复 spawn。"""
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    fake_icon = object()
    fake_item = object()
    with patch("qmt_gateway.tray._is_pid_alive_windows", return_value=True), \
         patch("qmt_gateway.tray._open_browser") as mock_open, \
         patch("qmt_gateway.tray._spawn_gateway") as mock_spawn:
        _start_gateway(fake_icon, fake_item)  # type: ignore[arg-type]
        mock_open.assert_called_once_with(fake_icon, fake_item)
        mock_spawn.assert_not_called()


def test_start_gateway_clears_stale_lock_before_spawn(home: Path):
    """.lock 指向死 PID（taskkill /F 没给 atexit 机会）→ 必须先清再 spawn。"""
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch("qmt_gateway.tray._is_pid_alive_windows", return_value=False), \
         patch("qmt_gateway.tray._clear_stale_lock") as mock_clear, \
         patch("qmt_gateway.tray._spawn_gateway") as mock_spawn:
        _start_gateway(None, None)  # type: ignore[arg-type]
        mock_clear.assert_called_once()
        mock_spawn.assert_called_once()


def test_restart_gateway_swallows_callback_exceptions(home: Path):
    """pystray 菜单回调抛异常时必须被 try/except 兜住——否则整个
    tray 消息循环挂掉，用户只能从任务管理器杀进程。"""
    (home / ".lock").write_text("99999\n", encoding="utf-8")
    with patch("qmt_gateway.tray._clear_stale_lock", side_effect=RuntimeError("boom")):
        # 不应抛出
        _restart_gateway(None, None)  # type: ignore[arg-type]


def test_start_gateway_swallows_callback_exceptions(home: Path):
    """同 test_restart_gateway_swallows_callback_exceptions。"""
    with patch("qmt_gateway.tray._clear_stale_lock", side_effect=RuntimeError("boom")):
        _start_gateway(None, None)  # type: ignore[arg-type]


# ---------- 集成测试 ----------
#
# 真实 spawn 一个 mock gateway 子进程，端到端验证 _start_gateway /
# _restart_gateway 的"停止后启动"路径。这个 mock 子进程不需要 QMT /
# xtquant（CI 没装）——它只是写 .lock / .port / 监听端口 / 收到 taskkill
# 清理退出，完全模拟 gateway 的最小行为。

_MOCK_GATEWAY_SCRIPT = r'''
"""测试用 mock gateway：模拟 qmt_gateway 的最小行为。

不依赖 QMT/xtquant，纯标准库。在 CI / dev 环境下替代真正的 gateway，
让 _start_gateway / _restart_gateway 可以被端到端测试。
"""
import atexit
import json
import os
import socket
import sys
import time

home = os.environ["MOCK_GATEWAY_HOME"]
port = int(os.environ.get("MOCK_GATEWAY_PORT", "0"))
lock_path = os.path.join(home, ".lock")
port_path = os.path.join(home, ".port")

# Find a free port
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.bind(("127.0.0.1", port))
port = srv.getsockname()[1]
srv.listen(5)
srv.settimeout(0.5)

pid = os.getpid()
lock_data = {"pid": pid, "started_at": time.time(), "argv_substring": "mock_gateway"}

with open(lock_path, "w", encoding="utf-8") as f:
    json.dump(lock_data, f)

with open(port_path, "w", encoding="utf-8") as f:
    f.write(f"{port}\n")


def cleanup():
    for p in (lock_path, port_path):
        try:
            os.remove(p)
        except OSError:
            pass


atexit.register(cleanup)
print(f"mock gateway pid={pid} port={port}", flush=True)

deadline = time.time() + 8  # 最多跑 8 秒
while time.time() < deadline:
    try:
        conn, _ = srv.accept()
        conn.close()
    except socket.timeout:
        pass
    except OSError:
        break

srv.close()
cleanup()
sys.exit(0)
'''


def _spawn_mock_gateway(home: Path, env_extra: dict | None = None, capture_output: bool = False) -> subprocess.Popen:
    """在临时 home 启动 mock gateway 子进程，返回 Popen 句柄。

    必须立刻返回——主进程不能阻塞在子进程上。
    """
    import sys as _sys

    env = os.environ.copy()
    env["MOCK_GATEWAY_HOME"] = str(home)
    if env_extra:
        env.update(env_extra)
    script_path = home / "_mock_gateway.py"
    script_path.write_text(_MOCK_GATEWAY_SCRIPT, encoding="utf-8")
    if capture_output:
        stdout = subprocess.PIPE
        stderr = subprocess.PIPE
    else:
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL
    return subprocess.Popen(
        [_sys.executable, str(script_path)],
        env=env,
        stdout=stdout,
        stderr=stderr,
    )


def _wait_for_lock_file(home: Path, timeout: float = 5.0) -> bool:
    """等 .lock 出现且包含有效 pid。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        lock = home / ".lock"
        if lock.is_file():
            try:
                data = json.loads(lock.read_text(encoding="utf-8"))
                pid = data.get("pid")
                if pid and pid > 0:
                    return True
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        time.sleep(0.05)
    return False


def _wait_for_port_listening(port: int, timeout: float = 5.0) -> bool:
    """等 TCP 端口就绪。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _cleanup_mock(proc: subprocess.Popen, home: Path) -> None:
    """收尾：kill mock gateway 子进程，等它退出。"""
    import time

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    # atexit 已经清 .lock / .port，这里防御性再清一次
    for name in (".lock", ".port", "_mock_gateway.py"):
        try:
            (home / name).unlink()
        except OSError:
            pass


def test_start_gateway_actually_spawns_running_child(home: Path):
    """端到端：_start_gateway 在过期 .lock + 无运行进程场景下，
    真正拉起一个 mock gateway 子进程，该子进程会写 .lock / .port 并
    监听端口。

    模拟用户场景：托盘"启动 QMT Gateway" → gateway 真的起来并被访问到。
    """
    # 场景：托盘被杀后启动，残留 .lock 指向死 pid（典型 stop 后状态）
    (home / ".lock").write_text(
        json.dumps({"pid": 99999, "started_at": 0.0, "argv_substring": "dead"}),
        encoding="utf-8",
    )

    # 注入真 spawn：让 _start_gateway 真的拉起 mock 子进程
    spawned_procs: list[subprocess.Popen] = []

    def real_spawn():
        p = _spawn_mock_gateway(home)
        spawned_procs.append(p)
        return True

    with patch("qmt_gateway.tray._spawn_gateway", side_effect=real_spawn):
        _start_gateway(None, None)  # type: ignore[arg-type]

    try:
        # 验证 mock 子进程写出了 .lock 和 .port
        assert _wait_for_lock_file(home, timeout=5.0), "mock gateway did not write .lock"
        assert (home / ".port").is_file(), "mock gateway did not write .port"
        port = int((home / ".port").read_text(encoding="utf-8").strip())
        assert _wait_for_port_listening(port, timeout=5.0), (
            f"mock gateway not listening on {port}"
        )
    finally:
        # 收尾 mock 子进程
        for p in spawned_procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()


def test_restart_gateway_kills_then_spawns_running_child(home: Path):
    """端到端：_restart_gateway 在已有 gateway 跑着时，
    先杀旧的、等端口空闲、再 spawn 新的。

    模拟用户场景：托盘"重启 QMT Gateway" → 旧 gateway 被 kill，新 gateway 起来。
    """
    # 先启动 mock 子进程作为"旧 gateway"
    old_proc = _spawn_mock_gateway(home)
    assert _wait_for_lock_file(home, timeout=5.0)
    port = int((home / ".port").read_text(encoding="utf-8").strip())
    assert _wait_for_port_listening(port, timeout=5.0)
    old_pid = json.loads((home / ".lock").read_text(encoding="utf-8"))["pid"]
    new_procs: list[subprocess.Popen] = []

    try:
        # 现在调 _restart_gateway。patch _spawn_gateway 让它真 spawn 一个新 mock。
        with patch("qmt_gateway.tray._spawn_gateway") as mock_spawn:
            def real_spawn():
                p = _spawn_mock_gateway(home, capture_output=True)
                new_procs.append(p)
                return True

            mock_spawn.side_effect = real_spawn
            _restart_gateway(None, None)  # type: ignore[arg-type]

        # 给新 mock 一点时间启动
        import time
        time.sleep(0.3)

        # 验证旧进程已死
        assert old_proc.poll() is not None, "old mock gateway should be killed"

        # 诊断输出
        for i, p in enumerate([old_proc] + new_procs):
            print(f"  proc[{i}] pid={p.pid} returncode={p.returncode}")
            if p.stdout and p.returncode is not None:
                out = p.stdout.read().decode("utf-8", errors="replace")[:500]
                err = p.stderr.read().decode("utf-8", errors="replace")[:500]
                print(f"    stdout={out!r}")
                print(f"    stderr={err!r}")
        print(f"  .lock={json.loads((home / '.lock').read_text(encoding='utf-8'))}")
        port_file = (home / ".port")
        print(f"  .port file exists={port_file.is_file()}")
        if port_file.is_file():
            print(f"  .port={port_file.read_text(encoding='utf-8')}")

        # 验证新进程在监听
        assert _wait_for_lock_file(home, timeout=5.0)
        new_lock = json.loads((home / ".lock").read_text(encoding="utf-8"))
        new_pid = new_lock["pid"]
        assert new_pid > 0, "new pid must be positive"
        new_port = int(port_file.read_text(encoding="utf-8").strip())
        assert _wait_for_port_listening(new_port, timeout=5.0)
    finally:
        # 收尾新旧 mock 子进程
        for p in [old_proc] + new_procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()