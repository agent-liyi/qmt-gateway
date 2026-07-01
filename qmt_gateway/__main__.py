"""命令行入口

提供 qmt-gateway 命令行工具。
"""

import argparse
import atexit
import ctypes
import ctypes.wintypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from qmt_gateway.access_log import configure_access_log
from qmt_gateway.config import config
from qmt_gateway.db import db
from qmt_gateway.runtime import runtime
from qmt_gateway.services.pip_mirror import ensure_pip_conf
from qmt_gateway.services.port import find_available_port


# ---------------------------------------------------------------------------
# 修复 build 76 安装器里 qmt-gateway 启动崩溃的问题。
#
# 现场：`task-launcher.log` 出现
#   AttributeError: module 'resource' has no attribute 'getrusage'
#   at apsw/ext.py:1109 in ShowResourceUsage
#
# 触发链：`from qmt_gateway.app import app` -> `from fasthtml.common import *`
#   -> `from apswutils import Database` -> `import apsw, apsw.ext, apsw.bestpractice`
#   -> `apsw/ext.py` 在 ShowResourceUsage 类体里 `import resource`，
#     然后 `_get_resource = resource.getrusage`。
#
# `apsw/ext.py` 用 `try / except ImportError:` 包住了这段——如果 `import resource`
# 抛 ImportError，except 会把 `_get_resource = None` 走掉。Windows 上
# `resource` 是 POSIX-only 模块，正常应该抛 ModuleNotFoundError（ImportError
# 子类）。
#
# 但在某些环境下（安装器在 scheduled task 里通过 wscript 拉起时复现），`import
# resource` 居然成功，但 `resource.getrusage` 不存在，导致 AttributeError
# 直接炸出来——而 `except ImportError:` 抓不住它。
#
# 修复策略：如果 sys.modules 里已经有一个 `resource` 但它没有 `getrusage`，
# 把它从 sys.modules 删掉，这样下次 `import resource` 会重新走模块查找，
# 找不到就抛 ImportError，让 apsw.ext 的 except 接管。
# ---------------------------------------------------------------------------
_existing_resource = sys.modules.get("resource")
if _existing_resource is not None and not hasattr(_existing_resource, "getrusage"):
    del sys.modules["resource"]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_OpenProcess = _kernel32.OpenProcess
_OpenProcess.restype = ctypes.wintypes.HANDLE
_OpenProcess.argtypes = [
    ctypes.wintypes.DWORD,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.DWORD,
]
_CloseHandle = _kernel32.CloseHandle
_CloseHandle.restype = ctypes.wintypes.BOOL
_CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _is_pid_alive(pid: int) -> bool:
    """检查指定 PID 的进程是否仍在运行（Windows）。

    用 ``OpenProcess`` + ``PROCESS_QUERY_LIMITED_INFORMATION`` 探测，避免
    引入 ``psutil``。返回 False 时可能是权限不足，但我们只关心"明确不存在"
    的情况——权限不足会让 OpenProcess 失败，我们仍然当作"进程不在"处理，
    反正也无法接管它的锁。
    """
    if pid <= 0:
        return False
    handle = _OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    _CloseHandle(handle)
    return True


def _pid_command_line(pid: int) -> str | None:
    """通过 WMI 拿指定 PID 的完整命令行。失败返回 None。

    用 PowerShell + CIM 是因为 pywin32 的 WMI 路径不在依赖里，而且
    PowerShell 在 Windows 10+ 自带。命令 1~2 秒返回，足够用来验证单实例锁。
    """
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' "
                f"| Select-Object -ExpandProperty CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = (result.stdout or "").strip()
    return out or None


def _pid_belongs_to_gateway(pid: int) -> bool:
    """``pid`` 仍在跑 + 它的命令行包含 ``qmt_gateway``——证明是我们的进程，
    而不是 PID 被 Windows 复用后巧合分配给另一个进程。

    这是单实例锁防 PID 冲突的关键。2026-06-30 现场：用户点托盘"停止" →
    gateway 死 → ``.lock`` 文件没及时清理（atexit 路径竞争） → 同号 PID
    被 smartscreen.exe 复用 → 新 gateway 启动时被 ``_is_pid_alive`` 误判为
    "另一个实例还在跑" → 退出码 2 → 用户从开始菜单启动无效。
    """
    if not _is_pid_alive(pid):
        return False
    cmd = _pid_command_line(pid)
    if cmd is None:
        # WMI 拿不到命令行（权限 / 进程已退出）——保守起见，假设不是我们的进程
        return False
    return "qmt_gateway" in cmd


def _read_lock_payload(lock_path: Path) -> dict[str, object] | None:
    """读 .lock 文件并解析为 dict。文件不存在 / 解析失败返回 None。

    锁文件结构：
        {"pid": <int>, "started_at": <float>, "argv_substring": "qmt_gateway"}

    老格式（裸 PID 数字）也能读，向后兼容。
    """
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    # 新格式：JSON
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                pid_value = payload.get("pid")
                if isinstance(pid_value, int):
                    return payload
        except (ValueError, TypeError):
            pass
        return None
    # 老格式：纯 PID 数字
    if raw.isdigit():
        return {"pid": int(raw), "started_at": 0.0, "argv_substring": ""}
    return None


def _acquire_single_instance_lock(home: Path) -> bool:
    """用 ``data\\home\\.lock`` 确保只有一个 gateway 进程在跑。

    锁文件里写 JSON ``{pid, started_at, argv_substring}``。后续启动时如果
    发现锁文件存在且对应进程仍是我们的（PID 活 + 命令行含 qmt_gateway），
    就直接返回 False，由调用方决定如何提示用户。否则清理掉重新占锁。

    用 ``O_CREAT | O_EXCL`` 原子创建，避免两个进程同时通过"检查+创建"的
    竞态条件。
    """
    lock_path = home / ".lock"
    pid = os.getpid()
    payload = {
        "pid": pid,
        "started_at": time.time(),
        "argv_substring": "qmt_gateway",
    }

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags, 0o644)
    except FileExistsError:
        # 锁文件已存在——解析它，判断是否还有效
        existing = _read_lock_payload(lock_path)
        if existing is None:
            # 文件损坏或不可读，删除后重试
            logger.warning("单实例锁文件损坏，清理后重试")
            try:
                lock_path.unlink()
            except OSError:
                logger.error("无法清理损坏的单实例锁文件")
                return False
            try:
                fd = os.open(str(lock_path), flags, 0o644)
            except FileExistsError:
                logger.error("锁文件被其他进程抢占，放弃本次启动")
                return False
        else:
            existing_pid = int(existing.get("pid", 0))
            if existing_pid > 0 and _pid_belongs_to_gateway(existing_pid):
                logger.error(
                    f"另一个 QMT Gateway 进程已在运行 (pid={existing_pid})，本次启动退出"
                )
                return False
            logger.warning(
                f"发现过期的单实例锁 (pid={existing_pid}，进程已不在或不是我们)，"
                f"清理后重新占锁"
            )
            try:
                lock_path.unlink()
            except OSError:
                logger.error("无法清理过期单实例锁文件，请手动删除")
                return False
            try:
                fd = os.open(str(lock_path), flags, 0o644)
            except FileExistsError:
                logger.error("锁文件被其他进程抢占，放弃本次启动")
                return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    logger.info(f"已获取单实例锁: {lock_path} (pid={pid})")
    return True


def _release_single_instance_lock(home: Path) -> None:
    """atexit 释放锁。只删自己写的锁，避免误删别人刚拿到的锁。"""
    lock_path = home / ".lock"
    try:
        if not lock_path.exists():
            return
        existing = _read_lock_payload(lock_path)
        if existing is None:
            return
        if int(existing.get("pid", 0)) == os.getpid():
            lock_path.unlink()
    except OSError:
        pass


def _write_port_file(port: int) -> None:
    r"""把实际监听的端口写到 ``data\home\.port``。

    桌面快捷方式 / 安装器的等待循环都依赖这个文件来知道真正可用的端口，
    避免 8130 被占用自动跳到 8131 之后快捷方式仍然打开 8130 而连不上的情况。
    """
    port_path = runtime.home_path / ".port"
    try:
        port_path.write_text(f"{port}\n", encoding="utf-8")
        logger.info(f"已写入端口文件: {port_path} ({port})")
    except Exception as exc:
        logger.warning(f"写入端口文件失败: {exc}")


def _remove_port_file() -> None:
    if not runtime.is_initialized():
        return
    port_path = runtime.home_path / ".port"
    try:
        if port_path.exists():
            port_path.unlink()
    except Exception:
        pass


def _is_tray_already_running() -> bool:
    """检查是否已有 qmt_gateway.tray 进程在跑（避免重复拉起多个托盘图标）。

    用 WMI 查 CommandLine 含 "qmt_gateway.tray" 的 python.exe 进程。
    只在 win32 上做检查；其它平台直接返回 False。
    """
    if sys.platform != "win32":
        return False
    import subprocess

    try:
        out = subprocess.check_output(
            'wmic process where "name=\'python.exe\'" get commandline /format:list',
            shell=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8", errors="replace")
    except (subprocess.SubprocessError, OSError):
        return False
    return "qmt_gateway.tray" in out


def _spawn_tray_process(home: Path) -> None:
    """拉起托盘子进程。

    托盘是独立进程而不是线程：pystray 的 win32 消息循环会阻塞当前线程，
    与 uvicorn 的 asyncio 事件循环互相干扰。独立进程最简单，也最稳。
    托盘会在父进程退出时被 job object 一起带走，所以不用担心孤儿进程。
    """
    if sys.platform != "win32":
        return

    # 避免重复拉起：如果已有一个 qmt_gateway.tray 进程在跑（用户从托盘
    # "重启"或从开始菜单再次启动 gateway），就不要再拉第二个——否则托盘
    # 区会叠加多个图标。用 WMI 查 CommandLine 含 "qmt_gateway.tray" 的
    # python.exe 进程。
    if _is_tray_already_running():
        logger.info("检测到已有托盘进程在运行，跳过拉起新托盘")
        return

    # 安装包里的 python 是 embeddable，没有 .pyc 缓存路径问题；
    # 这里走 sys.executable，等价于"和 gateway 同一个解释器"。
    env = os.environ.copy()
    env["QMT_GATEWAY_HOME"] = str(home)
    try:
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "qmt_gateway.tray"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=(
                subprocess.DETACHED_PROCESS  # noqa: F821
                | subprocess.CREATE_NEW_PROCESS_GROUP  # noqa: F821
            ),
        )
        logger.info("托盘进程已拉起")
    except OSError as exc:
        logger.warning(f"托盘进程拉起失败（不影响 gateway 运行）: {exc}")


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(
        description="QMT Gateway - 迅投QMT独立网关服务",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="服务器监听地址 (默认: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="服务器端口 (默认: 从配置读取，8130)",
    )
    parser.add_argument(
        "--init-wizard",
        action="store_true",
        help="强制显示初始化向导",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新初始化（配合 --init-wizard 使用）",
    )
    parser.add_argument(
        "--home",
        default=None,
        help="数据主目录 (默认: ~/.qmt-gateway)",
    )

    args = parser.parse_args()

    # 初始化运行时
    runtime.init(args.home)

    # 单实例锁：必须在写端口文件之前拿，否则两个进程都写 .port 后互相覆盖
    if not _acquire_single_instance_lock(runtime.home_path):
        sys.exit(2)
    atexit.register(_release_single_instance_lock, runtime.home_path)

    # 确保 pip 镜像源配置存在
    ensure_pip_conf()

    # 获取端口，若默认端口被占用则自动切换
    port = args.port or config.server_port
    try:
        port = find_available_port(default=port, max_tries=10, host=args.host)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    # 将实际使用的端口写回配置
    if port != config.server_port:
        try:
            config.set("server_port", port)
            logger.info(f"端口已更新为 {port}")
        except Exception:
            pass

    # 暴露端口文件，供 start.bat / 安装器等待循环读取
    _write_port_file(port)
    atexit.register(_remove_port_file)

    # 检查是否需要强制初始化
    if args.force and args.init_wizard:
        try:
            settings = db.get_settings()
            settings.init_completed = False
            settings.init_step = 0
            db.save_settings(settings)
            logger.info("已重置初始化状态")
        except Exception as e:
            logger.error(f"重置初始化状态失败: {e}")

    # 启动服务器
    logger.info(f"启动 QMT Gateway 服务器: http://{args.host}:{port}")

    import uvicorn

    configure_access_log(config.log_path)

    # 托盘子进程必须在 uvicorn 启动前拉起——uvicorn.run() 阻塞主线程，
    # 此后再 fork 会出问题。注意托盘是 *可选* 的：如果创建失败（比如
    # 跑在 Linux/macOS 调试环境、或 pystray 不可用），gateway 仍然要正常服务。
    _spawn_tray_process(runtime.home_path)

    uvicorn.run(
        "qmt_gateway.app:app",
        host=args.host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
