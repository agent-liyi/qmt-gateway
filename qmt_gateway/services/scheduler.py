"""定时任务调度器

提供定时更新股票列表、每日版本检查等功能。
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from qmt_gateway.config import config
from qmt_gateway.services.stock_service import stock_service


class TaskScheduler:
    """任务调度器"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self._initialized = False

    def start(self):
        """启动调度器"""
        if self._initialized:
            return

        # 每天早上 9:00 更新股票列表（开盘前）
        self.scheduler.add_job(
            func=self._update_stock_list,
            trigger=CronTrigger(hour=9, minute=0),
            id="update_stock_list",
            name="更新股票列表",
            replace_existing=True,
        )

        # 每天早上 10:00 检查版本更新
        self.scheduler.add_job(
            func=self._check_version_update,
            trigger=CronTrigger(hour=10, minute=0),
            id="check_version_update",
            name="检查版本更新",
            replace_existing=True,
        )

        # 每天早上 8:45 自动初始化 QMT（开盘前重启并登录）
        if config.auto_start_qmt:
            self.scheduler.add_job(
                func=self._daily_init_qmt,
                trigger=CronTrigger(hour=8, minute=45),
                id="daily_init_qmt",
                name="QMT 每日自动初始化",
                replace_existing=True,
            )

        # 启动时立即更新一次
        self._update_stock_list()

        self.scheduler.start()
        self._initialized = True
        logger.info("定时任务调度器已启动")

    def init_scheduler(self):
        """初始化调度器（兼容旧接口）"""
        self.start()

    def _update_stock_list(self):
        """更新股票列表任务"""
        logger.info("开始执行定时任务：更新股票列表")
        try:
            success = stock_service.update_stock_list()
            if success:
                logger.info("定时任务完成：股票列表更新成功")
            else:
                logger.warning("定时任务失败：股票列表更新失败")
        except Exception as e:
            logger.error(f"定时任务异常：{e}")

    def _check_version_update(self):
        """每日版本检查任务"""
        logger.info("开始执行定时任务：检查版本更新")
        try:
            from qmt_gateway.services.updater import check_update
            info = check_update()
            if info.has_update:
                logger.info(
                    f"发现新版本: {info.latest_version} (当前 {info.current_version})"
                )
            else:
                logger.debug(f"当前已是最新版本: {info.current_version}")
        except Exception as e:
            logger.error(f"版本检查异常：{e}")

    def _daily_init_qmt(self):
        """每日自动初始化 QMT：重启并登录，确保开盘前就绪"""
        logger.info("开始执行定时任务：QMT 每日自动初始化")
        try:
            from qmt_gateway.services.trade_service import trade_service
            account_id = str(trade_service._account_id or config.qmt_account_id or "").strip()
            qmt_path = str(trade_service._qmt_path or config.qmt_path or "").strip()
            if not account_id or not qmt_path:
                logger.warning("QMT 每日自动初始化：账号或路径未配置，跳过")
                return
            result = trade_service.try_auto_start_qmt(qmt_path=qmt_path, account_id=account_id)
            if result:
                logger.info("QMT 每日自动初始化：成功")
            else:
                logger.warning("QMT 每日自动初始化：失败")
        except Exception as e:
            logger.error(f"QMT 每日自动初始化异常：{e}")

    def stop(self):
        """停止调度器"""
        if self._initialized:
            self.scheduler.shutdown()
            self._initialized = False
            logger.info("定时任务调度器已关闭")

    def shutdown(self):
        """关闭调度器（兼容旧接口）"""
        self.stop()


# 全局调度器实例
scheduler = TaskScheduler()
