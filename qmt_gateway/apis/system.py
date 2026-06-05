"""系统管理 API

提供版本查询、内核更新、开机自启、端口信息等接口。
"""

import threading

from qmt_gateway.apis.auth import login_required
from qmt_gateway.config import config
from qmt_gateway.services.autostart import autostart_manager
from qmt_gateway.services.firewall import firewall_manager
from qmt_gateway.services.updater import (
    check_update,
    create_update_task,
    execute_update,
    get_update_task,
    rollback,
)


def register_routes(app) -> None:
    """注册系统管理路由"""

    @app.get("/api/system/version")
    @login_required
    def get_version(request):
        info = check_update()
        return {
            "code": 0,
            "data": {
                "current_version": info.current_version,
                "latest_version": info.latest_version,
                "has_update": info.has_update,
                "release_url": info.release_url,
                "error": info.error,
            },
        }

    @app.post("/api/system/version/check")
    @login_required
    def check_version(request):
        info = check_update()
        return {
            "code": 0,
            "data": {
                "current_version": info.current_version,
                "latest_version": info.latest_version,
                "has_update": info.has_update,
                "release_url": info.release_url,
                "error": info.error,
            },
        }

    @app.post("/api/system/update")
    @login_required
    def start_update(request):
        task_id = create_update_task()

        def _run():
            execute_update(task_id)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return {
            "code": 0,
            "data": {"task_id": task_id},
        }

    @app.get("/api/system/update/status/{task_id}")
    @login_required
    def get_update_status(request, task_id: str):
        task = get_update_task(task_id)
        if task is None:
            return {"code": 1, "message": f"任务不存在: {task_id}"}

        data = {
            "task_id": task.task_id,
            "status": task.status,
            "progress": task.progress,
        }
        if task.result:
            data["result"] = {
                "success": task.result.success,
                "old_version": task.result.old_version,
                "new_version": task.result.new_version,
                "error": task.result.error,
            }
        return {"code": 0, "data": data}

    @app.post("/api/system/rollback")
    @login_required
    def do_rollback(request):
        result = rollback()
        return {
            "code": 0 if result.success else 1,
            "data": {
                "success": result.success,
                "old_version": result.old_version,
                "new_version": result.new_version,
                "error": result.error,
            },
        }

    @app.get("/api/system/autostart")
    @login_required
    def get_autostart(request):
        return {
            "code": 0,
            "data": {"enabled": autostart_manager.is_enabled()},
        }

    @app.post("/api/system/autostart")
    @login_required
    async def set_autostart(request):
        form = await request.form()
        enabled = str(form.get("enabled", "")).lower() in ("true", "1", "on")

        if enabled:
            success = autostart_manager.enable()
        else:
            success = autostart_manager.disable()

        return {
            "code": 0 if success else 1,
            "data": {"enabled": autostart_manager.is_enabled()},
            "message": (
                "" if success
                else ("启用自启失败" if enabled else "禁用自启失败")
            ),
        }

    @app.get("/api/system/port")
    @login_required
    def get_port(request):
        return {
            "code": 0,
            "data": {"port": config.server_port},
        }

    @app.get("/api/system/firewall")
    @login_required
    def get_firewall(request):
        return {
            "code": 0,
            "data": {"rule_exists": firewall_manager.rule_exists()},
        }

    @app.post("/api/system/firewall")
    @login_required
    async def update_firewall(request):
        form = await request.form()
        port = int(form.get("port", config.server_port))
        success = firewall_manager.update_port(port)
        return {
            "code": 0 if success else 1,
            "data": {"rule_exists": firewall_manager.rule_exists()},
            "message": "" if success else "更新防火墙规则失败",
        }
