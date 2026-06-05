"""pip 国内镜像源配置

首次启动时自动创建 .venv/pip.conf，使用清华源加速 pip install。
"""

import sys
from pathlib import Path

from loguru import logger

DEFAULT_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
DEFAULT_TRUSTED_HOST = "pypi.tuna.tsinghua.edu.cn"


def get_pip_index_url() -> str:
    """获取 pip 镜像源地址

    优先读取已有的 pip.conf，否则返回默认清华源。
    """
    pip_conf = _find_pip_conf()
    if pip_conf and pip_conf.exists():
        try:
            content = pip_conf.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("index-url"):
                    return stripped.split("=", 1)[1].strip()
        except Exception:
            pass
    return DEFAULT_INDEX_URL


def ensure_pip_conf() -> bool:
    """确保 .venv/pip.conf 存在，不存在则自动创建

    Returns:
        是否创建或已存在

    """
    pip_conf = _find_pip_conf()
    if pip_conf is None:
        return False

    if pip_conf.exists():
        return True

    try:
        pip_conf.parent.mkdir(parents=True, exist_ok=True)
        pip_conf.write_text(
            f"[global]\n"
            f"index-url = {DEFAULT_INDEX_URL}\n"
            f"trusted-host = {DEFAULT_TRUSTED_HOST}\n",
            encoding="utf-8",
        )
        logger.info(f"已创建 pip 镜像源配置: {pip_conf}")
        return True
    except Exception as e:
        logger.warning(f"创建 pip.conf 失败: {e}")
        return False


def _find_pip_conf() -> Path | None:
    """定位 .venv/pip.conf 路径

    查找顺序：
    1. sys.prefix 下的 pip.conf（venv 内）
    2. 项目根目录下 .venv/pip.conf
    """
    venv_prefix = Path(sys.prefix)
    if (venv_prefix / "pyvenv.cfg").exists():
        return venv_prefix / "pip.conf"

    project_venv = Path(__file__).resolve().parent.parent.parent / ".venv"
    if (project_venv / "pyvenv.cfg").exists():
        return project_venv / "pip.conf"

    return None
