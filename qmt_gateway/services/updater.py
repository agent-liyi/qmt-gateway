"""版本检查与内核更新

- 查询当前版本（importlib.metadata / pyproject.toml）
- 查询 PyPI 最新版本
- 执行 pip 升级
- 备份与回滚
"""

import json
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from qmt_gateway.services.pip_mirror import get_pip_index_url

BACKUP_DIR_NAME = "version_backups"
MAX_BACKUPS = 3


@dataclass
class UpdateInfo:
    has_update: bool = False
    current_version: str = ""
    latest_version: str = ""
    release_url: str = ""
    error: str = ""


@dataclass
class UpdateResult:
    success: bool = False
    old_version: str = ""
    new_version: str = ""
    error: str = ""
    output: str = ""


@dataclass
class UpdateTask:
    task_id: str = ""
    status: str = "pending"
    progress: str = ""
    result: UpdateResult = field(default_factory=UpdateResult)


_update_tasks: dict[str, UpdateTask] = {}


def get_current_version() -> str:
    """获取当前安装的版本号"""
    try:
        from importlib.metadata import version
        return version("qmt-gateway")
    except Exception:
        pass

    try:
        pyproject = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        if pyproject.exists():
            for line in pyproject.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("version"):
                    return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass

    return "0.0.0"


def get_latest_version(timeout: int = 10) -> dict[str, Any]:
    """查询 PyPI 最新版本

    Returns:
        {"version": str, "release_url": str} 或 {"error": str}

    """
    try:
        url = "https://pypi.org/pypi/qmt-gateway/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        version = data["info"]["version"]
        release_url = (
            data["info"].get("release_url", "")
            or data["info"].get("project_url", "")
        )
        return {"version": version, "release_url": release_url}
    except Exception as e:
        logger.warning(f"查询 PyPI 最新版本失败: {e}")
        return {"error": str(e)}


def check_update(timeout: int = 10) -> UpdateInfo:
    """检查是否有新版本"""
    current = get_current_version()
    latest_result = get_latest_version(timeout=timeout)

    info = UpdateInfo(current_version=current)

    if "error" in latest_result:
        info.error = latest_result["error"]
        return info

    latest = latest_result["version"]
    info.latest_version = latest
    info.release_url = latest_result.get("release_url", "")

    try:
        from packaging.version import Version
        info.has_update = Version(latest) > Version(current)
    except Exception:
        info.has_update = latest != current

    return info


def _get_backup_dir() -> Path:
    """获取备份目录路径"""
    try:
        from qmt_gateway.runtime import runtime
        if runtime.is_initialized():
            return runtime.home_path / BACKUP_DIR_NAME
    except Exception:
        pass
    return Path.home() / ".qmt-gateway" / BACKUP_DIR_NAME


def _backup_current_version() -> Path | None:
    """备份当前版本的 site-packages/qmt_gateway"""
    try:
        import qmt_gateway
        pkg_dir = Path(qmt_gateway.__file__).resolve().parent
        if not pkg_dir.exists():
            return None

        backup_dir = _get_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)

        current_ver = get_current_version()
        dest = backup_dir / f"qmt_gateway-{current_ver}"
        if dest.exists():
            shutil.rmtree(dest)

        shutil.copytree(pkg_dir, dest)
        logger.info(f"已备份当前版本到 {dest}")
        _cleanup_old_backups(backup_dir)
        return dest
    except Exception as e:
        logger.error(f"备份当前版本失败: {e}")
        return None


def _cleanup_old_backups(backup_dir: Path) -> None:
    """清理旧备份，仅保留最近 MAX_BACKUPS 个"""
    try:
        backups = sorted(
            backup_dir.iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[MAX_BACKUPS:]:
            shutil.rmtree(old, ignore_errors=True)
            logger.info(f"已清理旧备份: {old.name}")
    except Exception:
        pass


def get_installed_versions() -> list[str]:
    """获取已备份的版本列表"""
    backup_dir = _get_backup_dir()
    if not backup_dir.exists():
        return []
    versions = []
    for d in backup_dir.iterdir():
        if d.is_dir() and d.name.startswith("qmt_gateway-"):
            versions.append(d.name.split("-", 1)[1])
    return sorted(versions, reverse=True)[:MAX_BACKUPS]


def _restore_backup(version: str) -> bool:
    """从备份恢复指定版本"""
    try:
        import qmt_gateway
        pkg_dir = Path(qmt_gateway.__file__).resolve().parent
        backup_dir = _get_backup_dir()
        backup_path = backup_dir / f"qmt_gateway-{version}"

        if not backup_path.exists():
            logger.error(f"备份不存在: {version}")
            return False

        parent = pkg_dir.parent
        tmp_dir = parent / "qmt_gateway_rollback_tmp"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)

        shutil.move(str(pkg_dir), str(tmp_dir))
        shutil.copytree(str(backup_path), str(pkg_dir))
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.info(f"已回滚到版本 {version}")
        return True
    except Exception as e:
        logger.error(f"回滚失败: {e}")
        return False


def execute_update(task_id: str) -> UpdateResult:
    """执行内核更新（pip install --upgrade）

    Args:
        task_id: 任务 ID

    Returns:
        更新结果

    """
    task = _update_tasks.get(task_id)
    if task is None:
        task = UpdateTask(task_id=task_id)
        _update_tasks[task_id] = task

    old_version = get_current_version()
    result = UpdateResult(old_version=old_version)

    try:
        task.status = "backing_up"
        task.progress = "正在备份当前版本..."
        _backup_current_version()

        task.status = "updating"
        task.progress = "正在执行 pip install --upgrade..."

        index_url = get_pip_index_url()
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--upgrade", "qmt-gateway",
            "-i", index_url,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        result.output = proc.stdout + proc.stderr

        if proc.returncode != 0:
            result.error = (
                f"pip install 失败 "
                f"(exit code {proc.returncode}): "
                f"{proc.stderr.strip()}"
            )
            task.status = "failed"
            task.progress = "更新失败"

            logger.warning("pip 升级失败，尝试回滚...")
            if _restore_backup(old_version):
                result.error += " (已回滚)"
            return result

        new_version = get_current_version()
        result.new_version = new_version
        result.success = True
        task.status = "completed"
        task.progress = f"更新完成: {old_version} → {new_version}"

        logger.info(f"内核更新完成: {old_version} → {new_version}")
    except Exception as e:
        result.error = str(e)
        task.status = "failed"
        task.progress = "更新失败"
        logger.error(f"内核更新异常: {e}")

    task.result = result
    return result


def rollback(version: str | None = None) -> UpdateResult:
    """回滚到指定版本（默认回滚到上一版本）

    Args:
        version: 目标版本号，为 None 时回滚到最近的备份

    Returns:
        回滚结果

    """
    if version is None:
        versions = get_installed_versions()
        current = get_current_version()
        for v in versions:
            if v != current:
                version = v
                break
        if version is None:
            return UpdateResult(error="没有可用的备份版本")

    old_version = get_current_version()
    success = _restore_backup(version)

    return UpdateResult(
        success=success,
        old_version=old_version,
        new_version=version if success else old_version,
        error="" if success else f"回滚到 {version} 失败",
    )


def get_update_task(task_id: str) -> UpdateTask | None:
    """获取更新任务状态"""
    return _update_tasks.get(task_id)


def create_update_task() -> str:
    """创建新的更新任务，返回 task_id"""
    import uuid
    task_id = str(uuid.uuid4())[:8]
    _update_tasks[task_id] = UpdateTask(
        task_id=task_id, status="pending", progress="等待执行",
    )
    return task_id
