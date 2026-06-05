"""防火墙规则管理

通过 netsh 管理 Windows 防火墙入站规则（仅 private profile）。
"""

import subprocess

from loguru import logger


class FirewallManager:
    """防火墙规则管理器"""

    RULE_NAME = "QMT Gateway"

    def rule_exists(self) -> bool:
        """检查防火墙规则是否已存在"""
        try:
            result = subprocess.run(
                [
                    "netsh", "advfirewall", "firewall", "show", "rule",
                    f"name={self.RULE_NAME}",
                ],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return result.returncode == 0 and self.RULE_NAME in result.stdout
        except Exception as e:
            logger.warning(f"查询防火墙规则失败: {e}")
            return False

    def add_rule(self, port: int) -> bool:
        """添加防火墙入站规则

        Args:
            port: 允许的端口号

        Returns:
            是否成功

        """
        try:
            result = subprocess.run(
                [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={self.RULE_NAME}",
                    "dir=in",
                    "action=allow",
                    "protocol=tcp",
                    f"localport={port}",
                    "profile=private",
                    "enable=yes",
                ],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                logger.info(f"已添加防火墙规则: {self.RULE_NAME} (端口 {port})")
                return True
            logger.error(f"添加防火墙规则失败: {result.stderr.strip()}")
            return False
        except Exception as e:
            logger.error(f"添加防火墙规则异常: {e}")
            return False

    def remove_rule(self) -> bool:
        """删除防火墙规则

        Returns:
            是否成功

        """
        try:
            result = subprocess.run(
                [
                    "netsh", "advfirewall", "firewall", "delete", "rule",
                    f"name={self.RULE_NAME}",
                ],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                logger.info(f"已删除防火墙规则: {self.RULE_NAME}")
                return True
            logger.error(f"删除防火墙规则失败: {result.stderr.strip()}")
            return False
        except Exception as e:
            logger.error(f"删除防火墙规则异常: {e}")
            return False

    def update_port(self, new_port: int) -> bool:
        """更新防火墙规则的端口号（先删后加）

        Args:
            new_port: 新端口号

        Returns:
            是否成功

        """
        if self.rule_exists():
            self.remove_rule()
        return self.add_rule(new_port)


firewall_manager = FirewallManager()
