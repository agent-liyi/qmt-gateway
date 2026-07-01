"""QMT Gateway 系统托盘图标。

启动后会在 Windows 系统托盘（任务栏右下角通知区）显示一个红色"匡"字图标，
右键菜单：

  - 打开管理界面  →  浏览器打开 http://localhost:<port>（.port 文件）
  - 启动 Gateway  →  停止后重新拉起 gateway（若已在跑则打开浏览器）
  - 重启 Gateway  →  杀掉旧 PID，等端口空闲，再启动新的 gateway
  - 停止 Gateway  →  杀掉 gateway 进程（托盘自身保留，可手动启动/重启）
  - 退出托盘      →  关闭托盘（gateway 继续运行）

入口由 ``__main__`` 在 lifespan startup 阶段以独立子进程拉起，确保
uvicorn 的事件循环不被 pystray 的 win32 消息循环阻塞。子进程在
gateway 退出时也会自动结束。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable

import pystray
from loguru import logger
from PIL import Image

# 注意：这些路径在模块导入时初始化——但在 Windows embeddable 环境下
# QMT_GATEWAY_HOME 是在 __main__.py 里 runtime.init() 之后才设置的。
# 因此下面的 *_path() 辅助函数每次调用都重读环境变量，确保配置和
# 运行时一致（__main__ 也会在拉起托盘前 export QMT_GATEWAY_HOME）。
def _home_path() -> Path:
    return Path(
        os.environ.get("QMT_GATEWAY_HOME", str(Path.home() / ".qmt-gateway"))
    )


def _lock_file() -> Path:
    return _home_path() / ".lock"


def _port_file() -> Path:
    return _home_path() / ".port"


# 保留旧名以兼容外部导入；新代码用 _lock_file() / _port_file()
LOCK_FILE = _lock_file()  # may be stale if env changes
PORT_FILE = _port_file()
ICON_PATH = Path(__file__).resolve().parent.parent / "installer" / "qmt-gateway.ico"


def _read_port() -> int:
    """读 .port 拿真实监听端口；没有就退回 8130。"""
    port_path = _port_file()
    try:
        if port_path.exists():
            raw = port_path.read_text(encoding="utf-8").strip()
            if raw.isdigit():
                return int(raw)
    except OSError:
        pass
    return 8130


def _read_pid() -> int | None:
    """读单实例锁文件拿 PID；不存在或读不到返回 None。

    锁文件可能是 JSON（新格式）或纯数字（旧格式）。
    """
    lock_path = _lock_file()
    try:
        if not lock_path.exists():
            return None
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    # 新格式：{"pid": 1234, ...}
    if raw.startswith("{"):
        try:
            import json

            payload = json.loads(raw)
            pid_value = payload.get("pid")
            if isinstance(pid_value, int):
                return pid_value
        except (ValueError, TypeError, ImportError):
            pass
        return None
    # 老格式：纯数字
    if raw.isdigit():
        return int(raw)
    return None


def _is_pid_alive_windows(pid: int) -> bool:
    """OpenProcess 探测 PID 是否存活（Windows 专用，避免依赖 psutil）。"""
    if sys.platform != "win32" or pid <= 0:
        return False
    import ctypes
    import ctypes.wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def _clear_stale_lock() -> None:
    """如果 .lock 指向的进程已经死了，把 .lock 和 .port 都删掉。

    场景：gateway 被 SIGKILL / 断电 / 任务管理器结束 → atexit 没机会跑 →
    残留 .lock 文件指向已不存在的 PID。新 gateway 启动时（无论是手动
    start.bat 还是托盘重启）会被这个过期的 .lock 挡住。
    """
    pid = _read_pid()
    if pid is None:
        return
    if _is_pid_alive_windows(pid):
        return
    # 进程已经死了，锁是过期的
    for path in (_lock_file(), _port_file()):
        try:
            if path.exists():
                path.unlink()
                logger.info(f"已清理过期文件: {path}")
        except OSError as exc:
            logger.warning(f"清理过期文件失败 {path}: {exc}")


def _kill_gateway(timeout: float = 5.0) -> bool:
    """杀掉 lock 文件里记录的 gateway 进程；返回是否成功。

    用 ``taskkill /F /PID``（不带 ``/T``）而不是带 ``/T`` 的进程树杀：
    - ``/T`` 会把 gateway 启动时 fork 的托盘子进程（即便它用了
      DETACHED_PROCESS / CREATE_NEW_PROCESS_GROUP）一起带走——结果用户
      点"停止"之后，托盘图标也消失，从开始菜单重启无效
    - 不带 ``/T`` 只杀 gateway 自己，托盘保持可见，可以继续监控或重启

    如果 .lock 指向的 PID 已经死了（gateway 被 kill -9 / 崩溃 / 断电），
    taskkill 会失败但这不算 error——此时清理掉过期的 .lock / .port，
    调用方可以继续 spawn 新 gateway。
    """
    pid = _read_pid()
    if pid is None:
        logger.warning("未找到单实例锁，跳过 kill")
        return False
    logger.info(f"正在终止 gateway 进程 (PID={pid})...")
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error("taskkill 超时")
        return False
    except FileNotFoundError:
        logger.error("taskkill 不在 PATH 上，无法终止进程")
        return False
    if result.returncode == 0:
        logger.info(f"gateway (PID={pid}) 已停止（托盘保持运行）")
        # 等 taskkill 真正生效（清理 kernel 句柄）
        time.sleep(0.3)
        return True
    # taskkill 失败：可能是 PID 已不存在——这正好是 stale lock 场景
    logger.warning(f"taskkill 返回 {result.returncode}: {result.stdout.strip()} {result.stderr.strip()}")
    if not _is_pid_alive_windows(pid):
        logger.info(f"PID {pid} 已不存在，清理过期单实例锁")
        _clear_stale_lock()
        return True
    return False


def _wait_for_port_free(port: int, timeout: float = 10.0) -> bool:
    """等待指定端口空闲。"""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                time.sleep(0.3)
    return False


def _spawn_gateway() -> bool:
    """启动一个新的 gateway 进程（用当前 Python 解释器）。"""
    python = sys.executable
    # 同一个 .exe、同一个 PYTHONPATH、同一个 QMT_GATEWAY_HOME
    env = os.environ.copy()
    try:
        subprocess.Popen(
            [python, "-m", "qmt_gateway"],
            env=env,
            creationflags=subprocess.DETACHED_PROCESS
            if sys.platform == "win32"
            else 0,
        )
        logger.info("新的 gateway 进程已拉起")
        return True
    except OSError as exc:
        logger.error(f"启动 gateway 失败: {exc}")
        return False


def _load_icon() -> Image.Image:
    """加载托盘图标；失败则退化为纯色方块。"""
    try:
        if ICON_PATH.is_file():
            return Image.open(ICON_PATH)
    except Exception as exc:
        logger.warning(f"加载图标失败 ({ICON_PATH}): {exc}，使用占位图")
    img = Image.new("RGBA", (32, 32), (209, 53, 39, 255))
    return img


def _open_browser(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    try:
        port = _read_port()
        url = f"http://localhost:{port}"
        logger.info(f"打开浏览器: {url}")
        webbrowser.open(url)
    except Exception as exc:
        logger.exception(f"打开浏览器失败: {exc}")


def _restart_gateway(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    try:
        logger.info("用户触发重启")
        # 先清过期锁（gateway 已被外部 kill -9 / 任务管理器结束的场景）
        _clear_stale_lock()
        # "停止"之后 gateway 已死、.lock 已被 atexit 删掉，_read_pid() 返回 None。
        # 此时 _kill_gateway() 返回 False，旧实现会短路掉 _spawn_gateway()——
        # 结果用户点"重启"什么也没发生。这里改成：没有正在跑的进程就直接拉起。
        # 注意不调 _wait_for_port_free：停止后 .port 已被删，_read_port() 退回
        # 8130，但 8130 可能被别的应用占用——此时等它空闲会误判为"端口占用"。
        # gateway 内部的 find_available_port 会自己探测可用端口，托盘不需要干预。
        pid = _read_pid()
        if pid is None:
            logger.info("未发现正在运行的 gateway，直接启动新实例")
            if not _spawn_gateway():
                logger.error("重启失败：spawn 返回 False")
            return
        port = _read_port()
        if _kill_gateway() and _wait_for_port_free(port, timeout=10.0):
            if not _spawn_gateway():
                logger.error("重启失败：spawn 返回 False")
        else:
            logger.warning("重启失败：旧进程未退出或端口仍占用")
    except Exception as exc:
        logger.exception(f"重启失败: {exc}")


def _stop_gateway(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    try:
        logger.info("用户触发停止")
        _kill_gateway()
    except Exception as exc:
        logger.exception(f"停止失败: {exc}")


def _quit_tray(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """退出托盘本身；gateway 继续运行（用户可从开始菜单重启托盘）。"""
    try:
        logger.info("退出托盘；gateway 保持运行")
        icon.stop()
    except Exception as exc:
        logger.exception(f"退出托盘失败: {exc}")


def _start_gateway(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """启动 gateway（停止后用来重新拉起服务）。

    与 _restart_gateway 的区别：这里假定当前没有正在运行的 gateway，
    不做 kill，直接 spawn。gateway 内部的 find_available_port 会自己
    探测可用端口，托盘不需要预先等端口空闲（否则 8130 被别的应用占用时
    会误判为"无法启动"）。
    """
    try:
        logger.info("用户触发启动")
        _clear_stale_lock()
        pid = _read_pid()
        if pid is not None and _is_pid_alive_windows(pid):
            # 已经在跑——直接打开浏览器，不重复拉起
            logger.info("gateway 已在运行，打开浏览器")
            _open_browser(icon, item)
            return
        if not _spawn_gateway():
            logger.error("启动失败：spawn 返回 False")
    except Exception as exc:
        logger.exception(f"启动失败: {exc}")


def _build_menu() -> pystray.Menu:
    return pystray.Menu(
        pystray.MenuItem("打开管理界面", _open_browser, default=True),
        pystray.MenuItem("启动 QMT Gateway", _start_gateway),
        pystray.MenuItem("重启 QMT Gateway", _restart_gateway),
        pystray.MenuItem("停止 QMT Gateway", _stop_gateway),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出托盘", _quit_tray),
    )


def run(
    on_ready: Callable[[], None] | None = None,
    on_stopped: Callable[[], None] | None = None,
) -> None:
    """同步入口：阻塞运行 pystray 消息循环。"""
    icon = pystray.Icon(
        "qmt-gateway",
        icon=_load_icon(),
        title="QMT Gateway",
        menu=_build_menu(),
    )
    # 在另一个线程里触发 on_ready，避免 pystray.detect_double_click
    # 之类的延迟回调阻塞启动
    if on_ready is not None:

        def _ready_signal():
            time.sleep(0.5)
            try:
                on_ready()
            except Exception as exc:
                logger.error(f"on_ready 回调异常: {exc}")

        threading.Thread(target=_ready_signal, daemon=True).start()

    try:
        icon.run()
    finally:
        if on_stopped is not None:
            try:
                on_stopped()
            except Exception as exc:
                logger.error(f"on_stopped 回调异常: {exc}")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    # 托盘是 DETACHED_PROCESS 启动的，stderr 在父进程上下文里没有可见
    # 的控制台——所有诊断信息会消失。这里把 INFO 及以上级别的日志镜像
    # 到 $INSTDIR\logs\tray.log（开发态为仓库根的 logs\tray.log），
    # 出问题时有据可查。
    try:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        # 安装态：qmt_gateway/tray.py 在 $INSTDIR\app\qmt_gateway\，
        # parent.parent 是 $INSTDIR\app，所以这里指向 app\logs。
        # 退而求其次写到 logs\tray.log（cwd 视角）。
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "tray.log",
            level="INFO",
            rotation="1 MB",
            retention=3,
            encoding="utf-8",
        )
    except OSError:
        pass
    logger.info("QMT Gateway 托盘启动")
    run()