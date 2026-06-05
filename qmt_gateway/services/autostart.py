"""开机自启管理

通过 Windows 任务计划程序 (schtasks) 管理开机自启任务。
"""

import subprocess

from loguru import logger


class AutoStartManager:
    """开机自启管理器"""

    TASK_NAME = "QMT Gateway"

    def __init__(self, script_path: str | None = None):
        self._script_path = script_path

    def is_enabled(self) -> bool:
        """检查开机自启任务是否已注册"""
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", self.TASK_NAME],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"查询自启任务失败: {e}")
            return False

    def enable(self, script_path: str | None = None) -> bool:
        """启用开机自启（注册 schtasks 任务）

        Args:
            script_path: start-silent.vbs 的完整路径

        Returns:
            是否成功

        """
        path = script_path or self._script_path
        if not path:
            logger.error("未提供启动脚本路径，无法注册自启任务")
            return False

        try:
            result = subprocess.run(
                [
                    "schtasks",
                    "/create",
                    "/tn", self.TASK_NAME,
                    "/tr", f'wscript.exe "{path}"',
                    "/sc", "onlogon",
                    "/rl", "limited",
                    "/f",
                ],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                logger.info(f"已注册开机自启任务: {self.TASK_NAME}")
                return True
            logger.error(f"注册自启任务失败: {result.stderr.strip()}")
            return False
        except Exception as e:
            logger.error(f"注册自启任务异常: {e}")
            return False

    def disable(self) -> bool:
        """禁用开机自启（删除 schtasks 任务）

        Returns:
            是否成功

        """
        try:
            result = subprocess.run(
                ["schtasks", "/delete", "/tn", self.TASK_NAME, "/f"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                logger.info(f"已删除开机自启任务: {self.TASK_NAME}")
                return True
            logger.error(f"删除自启任务失败: {result.stderr.strip()}")
            return False
        except Exception as e:
            logger.error(f"删除自启任务异常: {e}")
            return False


autostart_manager = AutoStartManager()
