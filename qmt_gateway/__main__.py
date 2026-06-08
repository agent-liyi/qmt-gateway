"""命令行入口

提供 qmt-gateway 命令行工具。
"""

import argparse
import sys

from loguru import logger

from qmt_gateway.config import config
from qmt_gateway.db import db
from qmt_gateway.runtime import runtime
from qmt_gateway.services.pip_mirror import ensure_pip_conf
from qmt_gateway.services.port import find_available_port


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

    import logging
    import uvicorn

    logging.getLogger("uvicorn.access").setLevel(logging.DEBUG)

    uvicorn.run(
        "qmt_gateway.app:app",
        host=args.host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
