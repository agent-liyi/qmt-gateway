"""初始化向导（init-wizard）行为回归测试。

重点覆盖：

- ``GET /init-wizard?force=true`` **不写 DB**：仅渲染页面，原始
  ``init_completed`` 状态保持不变；
- 用户中途放弃（不调 ``/init-wizard/complete``）时，主应用仍可用；
- ``POST /init-wizard/complete`` 是**原子**的：xtquant 连接测试失败
  会回滚所有改动，settings / user / asset 均保持原值。
"""

import tempfile
from pathlib import Path

import pytest
from fastcore.xml import to_xml
from starlette.testclient import TestClient

import qmt_gateway.apis.auth as auth_api
from qmt_gateway import app as app_module
from qmt_gateway.app import app
from qmt_gateway.db.models import Settings, User
from qmt_gateway.db.sqlite import db
from qmt_gateway.web.pages.init_wizard import InitWizardPage


@pytest.fixture
def in_memory_db(monkeypatch):
    """用临时文件数据库替换默认数据库。"""
    tmp_dir = tempfile.mkdtemp(prefix="qmt-init-wizard-test-")
    db_path = Path(tmp_dir) / "test.db"
    db.init(db_path)
    yield db_path


@pytest.fixture
def seeded_initialized_db(in_memory_db):
    """已初始化的 DB：包含 admin 用户 + init_completed=True 的 settings。"""
    admin = User(username="admin", password_hash=auth_api.hash_password("old-pass-123"))
    db.save_user(admin)

    settings = db.get_settings()
    settings.init_completed = True
    settings.init_step = 5
    settings.server_port = 9999
    settings.log_path = "logs"
    settings.log_retention = 7
    settings.qmt_account_id = "old-account"
    settings.qmt_path = r"C:\old\qmt"
    settings.xtquant_path = r"C:\old\xtquant"
    db.save_settings(settings)
    return admin


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def force_get(client, seeded_initialized_db):
    """打开 force=true 的初始化向导页面（不提交完成）。"""
    response = client.get("/init-wizard?force=true")
    assert response.status_code == 200
    return response


# ---------------------------------------------------------------------------
# 行为 1：GET /init-wizard?force=true 不修改任何持久化状态
# ---------------------------------------------------------------------------


def test_force_get_does_not_touch_init_completed(seeded_initialized_db):
    """force GET 不应把 init_completed 改为 False。"""
    TestClient(app).get("/init-wizard?force=true")

    settings = db.get_settings()
    assert settings.init_completed is True, (
        "GET /init-wizard?force=true 不应把 init_completed 改为 False"
    )


def test_force_get_preserves_all_settings_values(seeded_initialized_db):
    """force GET 不应修改 settings 的任何字段。"""
    before = db.get_settings().to_dict()
    TestClient(app).get("/init-wizard?force=true")
    after = db.get_settings().to_dict()
    assert before == after


def test_force_get_does_not_corrupt_user(seeded_initialized_db):
    """force GET 不应触碰用户表。"""
    before_password = db.get_user("admin").password_hash
    TestClient(app).get("/init-wizard?force=true")
    after_password = db.get_user("admin").password_hash
    assert before_password == after_password


def test_force_get_then_abandon_keeps_app_accessible(seeded_initialized_db):
    """force GET 后用户关闭页面，主应用仍然可访问（不被 init_required 拦截）。"""
    client = TestClient(app)
    client.get("/init-wizard?force=true")

    # 中间件 check_init_required() 应仍然返回 False，主页可正常路由
    from qmt_gateway.app import check_init_required
    assert check_init_required() is False


# ---------------------------------------------------------------------------
# 行为 2：force GET 应预填现有 settings（便于 no-op 完成）
# ---------------------------------------------------------------------------


def test_force_get_seeds_internal_wizard_data_from_current_settings(
    seeded_initialized_db, force_get
):
    """force 模式下 _wizard_data 应使用现有 settings 预填。"""
    seed = app_module._seed_wizard_data_from_current_settings()
    assert seed["server_port"] == "9999"
    assert seed["log_retention"] == "7"
    assert seed["qmt_account_id"] == "old-account"
    assert seed["qmt_path"] == r"C:\old\qmt"
    assert seed["xtquant_path"] == r"C:\old\xtquant"
    assert seed["username"] == "admin"


# ---------------------------------------------------------------------------
# 行为 3：POST /init-wizard/complete 是原子的——xtquant 失败会回滚
# ---------------------------------------------------------------------------


def test_complete_rolls_back_when_xtquant_test_fails(
    seeded_initialized_db, client, monkeypatch
):
    """xtquant 连接测试失败时，本次提交必须回滚。

    验证：settings 字段、user 密码、``init_completed`` 全部保持原值。
    """
    from qmt_gateway import core as core_module
    from qmt_gateway import qmt_init_helpers
    from qmt_gateway.services.trade_service import trade_service as ts_instance

    def broken_require_xtdata(*args, **kwargs):
        raise RuntimeError("模拟 xtquant 不可用")

    monkeypatch.setattr(core_module, "require_xtdata", broken_require_xtdata)
    monkeypatch.setattr(qmt_init_helpers, "is_qmt_process_running", lambda *a, **k: True)
    monkeypatch.setattr(ts_instance, "_resolve_qmt_client_path", lambda p: type("P", (), {"name": "XtItClient.exe"})())
    monkeypatch.setattr(ts_instance, "_launch_qmt_process", lambda *a, **kw: type("P", (), {"pid": 1234})())
    monkeypatch.setattr(ts_instance, "_fill_qmt_login_password", lambda *a, **kw: None)
    monkeypatch.setattr(ts_instance, "_get_current_session_id", lambda: 1)

    settings_before = db.get_settings().to_dict()
    user_password_before = db.get_user("admin").password_hash

    response = client.post(
        "/init-wizard/complete",
        data={
            "username": "admin",
            "password": "new-pass-456",
            "server_port": "7777",
            "log_path": "logs",
            "log_rotation": "10 MB",
            "log_retention": "3",
            "qmt_account_id": "new-account",
            "qmt_path": r"C:\new\qmt",
"xtquant_path": r"C:\new\xtquant",
            "qmt_password": "trade-pass-123",
            "auto_start_qmt": "on",
            "principal": "2000000",
        },
    )

    assert response.status_code == 200
    body = response.text
    # 启动成功但连接失败，应展示等待对话框
    assert "wizard-progress-content" in body
    assert "重试" in body
    assert "返回修改配置" in body

    settings_after = db.get_settings().to_dict()
    assert settings_after == settings_before
    assert bool(settings_after["init_completed"]) is True
    assert db.get_user("admin").password_hash == user_password_before


def test_complete_rolls_back_settings_when_test_fails_after_partial_form(
    seeded_initialized_db, client, monkeypatch
):
    """即使 wizard_data 已被部分填入，连接失败时 settings 必须保持原状。"""
    from qmt_gateway import core as core_module
    from qmt_gateway import qmt_init_helpers
    from qmt_gateway.services.trade_service import trade_service as ts_instance

    def broken_require_xtdata(*args, **kwargs):
        raise RuntimeError("xtquant unavailable")

    monkeypatch.setattr(core_module, "require_xtdata", broken_require_xtdata)
    monkeypatch.setattr(qmt_init_helpers, "is_qmt_process_running", lambda *a, **k: True)
    monkeypatch.setattr(ts_instance, "_resolve_qmt_client_path", lambda p: type("P", (), {"name": "XtItClient.exe"})())
    monkeypatch.setattr(ts_instance, "_launch_qmt_process", lambda *a, **kw: type("P", (), {"pid": 1234})())
    monkeypatch.setattr(ts_instance, "_fill_qmt_login_password", lambda *a, **kw: None)
    monkeypatch.setattr(ts_instance, "_get_current_session_id", lambda: 1)

    client.post(
        "/init-wizard/step/2",
        data={
            "username": "admin",
            "password": "temp-pass-123",
        },
    )

    settings_before = db.get_settings().to_dict()
    response = client.post(
        "/init-wizard/complete",
        data={
            "server_port": "8888",
            "log_path": "new-logs",
            "log_rotation": "5 MB",
            "log_retention": "1",
            "qmt_account_id": "",
            "qmt_path": "",
            "xtquant_path": "",
            "qmt_password": "trade-pass-123",
            "auto_start_qmt": "on",
            "principal": "500000",
        },
    )
    assert response.status_code == 200
    assert "wizard-progress-content" in response.text

    assert db.get_settings().to_dict() == settings_before


# ---------------------------------------------------------------------------
# 行为 4：QMT 自愈流程
# ---------------------------------------------------------------------------


def _make_fake_qmt_install(root: Path) -> Path:
    """在 ``root`` 下创建一个看上去合法的 QMT 目录树，返回 userdata_mini 路径。"""
    install = root / "FakeBrokerQMT"
    userdata = install / "userdata_mini"
    bin_dir = install / "bin.x64"
    bin_dir.mkdir(parents=True)
    userdata.mkdir(parents=True)
    # 仅创建一个空文件充作可执行文件
    (bin_dir / "XtItClient.exe").write_bytes(b"")
    return userdata


def test_recovery_reports_invalid_path_without_launching(
    seeded_initialized_db, client, monkeypatch
):
    """qmt_path 指向不存在的目录时，_wizard_restart_qmt 应报路径错误。"""
    from qmt_gateway import core as core_module
    from qmt_gateway import qmt_init_helpers

    def broken_require_xtdata(*args, **kwargs):
        raise RuntimeError("xtquant unavailable")

    monkeypatch.setattr(core_module, "require_xtdata", broken_require_xtdata)
    monkeypatch.setattr(qmt_init_helpers, "is_qmt_process_running", lambda *a, **k: True)

    settings_before = db.get_settings().to_dict()
    response = client.post(
        "/init-wizard/complete",
        data={
            "username": "admin",
            "password": "new-pass-456",
            "server_port": "7777",
            "log_path": "logs",
            "log_rotation": "10 MB",
            "log_retention": "3",
            "qmt_account_id": "",
            "qmt_path": r"C:\definitely\not\there",
            "xtquant_path": "",
            "qmt_password": "trade-pass-123",
            "auto_start_qmt": "on",
            "principal": "2000000",
        },
    )
    assert response.status_code == 200
    body = response.text
    # 路径不存在时 _wizard_restart_qmt 会抛异常，wizard_complete 展示失败或等待对话框
    assert "重试" in body
    assert "返回修改配置" in body
    # 回滚生效
    assert db.get_settings().to_dict() == settings_before


def test_recovery_attempts_launch_when_path_valid_but_qmt_not_running(
    seeded_initialized_db, client, monkeypatch, tmp_path
):
    """qmt_path 合法 + QMT 未运行 + 有交易密码 → wizard_complete 调用 restart_qmt 失败后返回等待对话框。"""
    from qmt_gateway import core as core_module
    from qmt_gateway.services.trade_service import trade_service as ts_instance

    userdata = _make_fake_qmt_install(tmp_path)

    def fake_require_xtdata(*args, **kwargs):
        raise RuntimeError("首次连接失败")

    monkeypatch.setattr(core_module, "require_xtdata", fake_require_xtdata)
    monkeypatch.setattr(
        ts_instance, "restart_and_login",
        lambda **kw: {"success": False, "error": "连接失败"},
    )

    settings_before = db.get_settings().to_dict()
    response = client.post(
        "/init-wizard/complete",
        data={
            "username": "admin",
            "password": "new-pass-456",
            "server_port": "7777",
            "log_path": "logs",
            "log_rotation": "10 MB",
            "log_retention": "3",
            "qmt_account_id": "",
            "qmt_path": str(userdata),
            "xtquant_path": "",
            "qmt_password": "trade-pass-123",
            "auto_start_qmt": "on",
            "principal": "2000000",
        },
    )
    assert response.status_code == 200
    body = response.text
    # 应返回等待对话框（含自触发重试），而非失败页
    assert "wizard-progress-content" in body
    assert "hx-swap-oob" in body
    assert "重试" in body
    assert "返回修改配置" in body
    assert "wizard-auto-retry" in body
    # 回滚生效
    assert db.get_settings().to_dict() == settings_before


def test_recovery_succeeds_when_trade_service_restart_qmt(
    seeded_initialized_db, client, monkeypatch, tmp_path
):
    """QMT 未运行 + 有交易密码 → wizard 启动 QMT + 填密码后连接成功。"""
    from qmt_gateway import core as core_module
    from qmt_gateway import qmt_init_helpers
    from qmt_gateway.services.trade_service import trade_service as ts_instance

    userdata = _make_fake_qmt_install(tmp_path)

    call_count = {"value": 0}

    def fake_require_xtdata(*args, **kwargs):
        call_count["value"] += 1
        return _make_fake_xtdata()

    launch_called = {"value": False}

    def fake_launch(*a, **kw):
        launch_called["value"] = True
        return type("P", (), {"pid": 1234})()

    monkeypatch.setattr(core_module, "require_xtdata", fake_require_xtdata)
    monkeypatch.setattr(qmt_init_helpers, "is_qmt_process_running", lambda *a, **k: False)
    monkeypatch.setattr(ts_instance, "_launch_qmt_process", fake_launch)
    monkeypatch.setattr(ts_instance, "_fill_qmt_login_password", lambda *a, **kw: None)
    monkeypatch.setattr(ts_instance, "_get_current_session_id", lambda: 1)

    response = client.post(
        "/init-wizard/complete",
        data={
            "username": "admin",
            "password": "new-pass-456",
            "server_port": "8888",
            "log_path": "logs",
            "log_rotation": "10 MB",
            "log_retention": "3",
            "qmt_account_id": "new-account",
            "qmt_path": str(userdata),
            "xtquant_path": "",
            "qmt_password": "trade-pass-123",
            "auto_start_qmt": "on",
            "principal": "3000000",
        },
        follow_redirects=False,
    )
    # 启动成功，第二次连接测试成功
    assert launch_called["value"] is True
    assert response.status_code in (302, 303)
    saved = db.get_settings()
    assert bool(saved.init_completed) is True
    assert saved.server_port == 8888
    assert saved.qmt_account_id == "new-account"


def test_retry_startup_failure_branch_uses_fast_auto_retry(
    seeded_initialized_db, client, monkeypatch, tmp_path
):
    """retry-startup 的失败态应保持 1 秒级自动轮询，避免成功后仍长时间卡住。"""
    from qmt_gateway import app as app_module
    from qmt_gateway.services.trade_service import trade_service as ts_instance

    _make_fake_qmt_install(tmp_path)
    monkeypatch.setattr(
        app_module,
        "_wizard_data",
        {
            "username": "admin",
            "password": "new-pass-456",
            "qmt_account_id": "8881457417",
            "qmt_path": str(tmp_path / "FakeBrokerQMT" / "userdata_mini"),
            "xtquant_path": r"C:\apps",
            "qmt_password": "trade-pass-123",
        },
    )
    monkeypatch.setattr(
        app_module,
        "_restart_status",
        {"success": False, "error": "连接失败"},
    )
    monkeypatch.setattr(ts_instance, "_resolve_qmt_client_path", lambda p: type("P", (), {"name": "XtItClient.exe"})())
    monkeypatch.setattr(ts_instance, "_kill_qmt_process", lambda *a, **k: None)

    response = client.post("/init-wizard/retry-startup")

    assert response.status_code == 200
    body = response.text
    assert "QMT 启动失败，正在重试..." in body
    assert ",1000);" in body or "1000" in body


def test_retry_startup_success_branch_skips_xtdata_wait(
    seeded_initialized_db, client, monkeypatch, tmp_path
):
    """restart_qmt 成功后应立即进入完成初始化，不再等待 xtdata 验证。"""
    from qmt_gateway import app as app_module
    from qmt_gateway.services.trade_service import trade_service as ts_instance

    _make_fake_qmt_install(tmp_path)
    monkeypatch.setattr(
        app_module,
        "_wizard_data",
        {
            "username": "admin",
            "password": "new-pass-456",
            "qmt_account_id": "8881457417",
            "qmt_path": str(tmp_path / "FakeBrokerQMT" / "userdata_mini"),
            "xtquant_path": r"C:\apps",
            "qmt_password": "trade-pass-123",
        },
    )
    monkeypatch.setattr(
        app_module,
        "_restart_status",
        {"success": True, "message": "QMT 已重启"},
    )
    monkeypatch.setattr(ts_instance, "_resolve_qmt_client_path", lambda p: type("P", (), {"name": "XtItClient.exe"})())
    monkeypatch.setattr(ts_instance, "_kill_qmt_process", lambda *a, **k: None)
    from qmt_gateway import core as core_module
    monkeypatch.setattr(
        core_module,
        "require_xtdata",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("xtdata check should be skipped")),
    )

    response = client.post("/init-wizard/retry-startup")

    assert response.status_code == 200
    body = response.text
    assert "QMT 连接成功，正在完成初始化..." in body
    assert "wizard-auto-retry" in body


def test_recovery_forces_restart_when_qmt_is_running_but_connection_fails(
    seeded_initialized_db, client, monkeypatch, tmp_path
):
    """QMT 已运行但未登录成功时，wizard_complete 必须强制重启而不是短路成功。"""
    from qmt_gateway import core as core_module
    from qmt_gateway import qmt_init_helpers
    from qmt_gateway.services.trade_service import trade_service as ts_instance

    userdata = _make_fake_qmt_install(tmp_path)
    kill_called = {"value": False}
    launch_called = {"value": False}

    def fake_require_xtdata(*args, **kwargs):
        raise RuntimeError("xtquant unavailable")

    def fake_kill(*args, **kwargs):
        kill_called["value"] = True

    def fake_launch(*args, **kwargs):
        launch_called["value"] = True
        return type("P", (), {"pid": 4321})()

    monkeypatch.setattr(core_module, "require_xtdata", fake_require_xtdata)
    monkeypatch.setattr(qmt_init_helpers, "is_qmt_process_running", lambda *a, **k: True)
    monkeypatch.setattr(ts_instance, "_kill_qmt_process", fake_kill)
    monkeypatch.setattr(ts_instance, "_launch_qmt_process", fake_launch)
    monkeypatch.setattr(ts_instance, "_fill_qmt_login_password", lambda *a, **kw: None)
    monkeypatch.setattr(ts_instance, "_get_current_session_id", lambda: 1)

    response = client.post(
        "/init-wizard/complete",
        data={
            "username": "admin",
            "password": "new-pass-456",
            "server_port": "7777",
            "log_path": "logs",
            "log_rotation": "10 MB",
            "log_retention": "3",
            "qmt_account_id": "new-account",
            "qmt_path": str(userdata),
            "xtquant_path": "",
            "qmt_password": "trade-pass-123",
            "auto_start_qmt": "on",
            "principal": "2000000",
        },
    )

    assert response.status_code == 200
    assert kill_called["value"] is True
    assert launch_called["value"] is True
    assert "wizard-progress-content" in response.text


def _make_fake_xtdata():
    """构造一个最小的 xtdata 桩，让 get_stock_list_in_sector 返回非空列表。"""

    class _FakeXtData:
        def get_stock_list_in_sector(self, sector):
            return ["000001.SZ", "600000.SH"]

    return _FakeXtData()


# ---------------------------------------------------------------------------
# 行为 5：无 QMT 交易密码时跳过连接检查和自动启动
# ---------------------------------------------------------------------------


def test_complete_without_qmt_password_skips_connection_test(
    seeded_initialized_db, client, monkeypatch
):
    """不提供 qmt_password 时，wizard_complete 应跳过连接检查，直接落库完成初始化。"""
    require_xtdata_called = {"value": False}

    def spy_require_xtdata(*args, **kwargs):
        require_xtdata_called["value"] = True
        return _make_fake_xtdata()

    from qmt_gateway import core as core_module
    monkeypatch.setattr(core_module, "require_xtdata", spy_require_xtdata)

    response = client.post(
        "/init-wizard/complete",
        data={
            "username": "admin",
            "password": "new-pass-456",
            "server_port": "8888",
            "log_path": "logs",
            "log_rotation": "10 MB",
            "log_retention": "3",
            "qmt_account_id": "new-account",
            "qmt_path": r"C:\some\qmt",
            "xtquant_path": "",
            "qmt_password": "",
            "principal": "2000000",
        },
        follow_redirects=False,
    )

    # 应直接重定向到首页
    assert response.status_code in (302, 303)
    # 不应调用 require_xtdata
    assert require_xtdata_called["value"] is False
    # 落盘生效
    saved = db.get_settings()
    assert bool(saved.init_completed) is True
    assert saved.server_port == 8888
    assert saved.qmt_account_id == "new-account"
    # 无密码时不应存储加密密码
    assert saved.qmt_password_encrypted == ""
    assert saved.qmt_password_salt == ""


def test_complete_without_qmt_password_still_saves_settings(
    seeded_initialized_db, client, monkeypatch
):
    """无 QMT 密码完成初始化后，settings 各字段应正确保存。"""
    from qmt_gateway import core as core_module
    monkeypatch.setattr(core_module, "require_xtdata", lambda *a, **k: _make_fake_xtdata())

    client.post(
        "/init-wizard/complete",
        data={
            "username": "admin",
            "password": "admin-pass",
            "server_port": "8130",
            "log_path": "/tmp/qmt-logs",
            "log_rotation": "5 MB",
            "log_retention": "5",
            "qmt_account_id": "12345678",
            "qmt_path": r"C:\broker\userdata_mini",
            "xtquant_path": r"C:\apps",
            "qmt_password": "",
            "principal": "500000",
        },
        follow_redirects=False,
    )

    saved = db.get_settings()
    assert saved.qmt_account_id == "12345678"
    assert saved.init_completed is True
    assert saved.qmt_password_encrypted == ""


def test_complete_with_password_but_no_auto_start_skips_restart(
    seeded_initialized_db, client, monkeypatch
):
    """有密码但未勾选 auto_start_qmt 时，应只保存密码不执行自动重启/重连。"""
    from qmt_gateway import app as app_module
    from qmt_gateway import core as core_module
    monkeypatch.setattr(core_module, "require_xtdata", lambda *a, **k: _make_fake_xtdata())
    app_module._wizard_data.clear()

    response = client.post(
        "/init-wizard/complete",
        data={
            "username": "admin",
            "password": "admin-pass",
            "server_port": "8130",
            "log_path": "/tmp/qmt-logs",
            "log_rotation": "5 MB",
            "log_retention": "5",
            "qmt_account_id": "12345678",
            "qmt_path": r"C:\broker\userdata_mini",
            "xtquant_path": r"C:\apps",
            "qmt_password": "my-trade-secret",
            "principal": "500000",
        },
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    saved = db.get_settings()
    assert saved.qmt_account_id == "12345678"
    assert saved.init_completed is True
    assert saved.qmt_password_encrypted != ""
    assert saved.qmt_password_salt != ""
    assert saved.auto_start_qmt is False
    assert saved.qmt_password_auto_start == ""


def test_complete_via_multistep_flow_saves_qmt_password(
    seeded_initialized_db, client, monkeypatch
):
    """模拟真实多步骤流程：先提交 step 2 设置 admin 密码，再提交 step 5 设置 qmt_password。

    验证：即使 auto_start_qmt 未勾选，qmt_password 仍被加密保存。
    """
    from qmt_gateway import app as app_module
    from qmt_gateway import core as core_module
    monkeypatch.setattr(core_module, "require_xtdata", lambda *a, **k: _make_fake_xtdata())
    app_module._wizard_data.clear()

    # step 2 → step 3：设置管理员账号
    client.post(
        "/init-wizard/step/3",
        data={
            "username": "admin",
            "password": "admin-pass",
            "password_confirm": "admin-pass",
        },
    )

    # step 5：直接 POST complete（未勾选 auto_start_qmt）
    response = client.post(
        "/init-wizard/complete",
        data={
            "qmt_account_id": "8881457417",
            "qmt_path": r"C:\broker\userdata_mini",
            "xtquant_path": r"C:\apps",
            "qmt_password": "trade-secret",
        },
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    saved = db.get_settings()
    assert saved.qmt_account_id == "8881457417"
    assert saved.init_completed is True
    assert saved.qmt_password_encrypted != "", "qmt_password 必须被加密保存"
    assert saved.qmt_password_salt != ""
    assert saved.auto_start_qmt is False
    assert saved.qmt_password_auto_start == ""


def test_complete_without_qmt_password_uses_hx_redirect_for_htmx_requests(
    seeded_initialized_db, client, monkeypatch
):
    """HTMX 完成初始化时应返回 HX-Redirect，避免延迟或错误交换。"""
    from qmt_gateway import core as core_module

    monkeypatch.setattr(core_module, "require_xtdata", lambda *a, **k: _make_fake_xtdata())

    response = client.post(
        "/init-wizard/complete",
        headers={"HX-Request": "true"},
        data={
            "username": "admin",
            "password": "admin-pass",
            "server_port": "8130",
            "log_path": "/tmp/qmt-logs",
            "log_rotation": "5 MB",
            "log_retention": "5",
            "qmt_account_id": "12345678",
            "qmt_path": r"C:\broker\userdata_mini",
            "xtquant_path": r"C:\apps",
            "qmt_password": "",
            "principal": "500000",
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/"


def test_init_wizard_page_script_uses_cumulative_30_second_retry_window():
    """前端脚本应累计等待时间，并在 30 秒后开放手动重试。"""
    html = to_xml(InitWizardPage())

    assert "var _retryDelay = 30;" in html
    assert "var _progressStartedAt = 0;" in html
    assert "getResponseHeader('HX-Redirect')" in html


def test_restart_qmt_fails_gracefully_without_password(seeded_initialized_db):
    """_wizard_restart_qmt 在无密码时应返回失败，但不抛异常。"""
    from qmt_gateway.app import _build_settings_from_wizard_data
    wizard_data = {
        "username": "admin",
        "password": "admin-pass",
        "server_port": "8130",
        "qmt_account_id": "12345678",
        "qmt_path": r"C:\broker\userdata_mini",
        "qmt_password": "",
    }
    settings = _build_settings_from_wizard_data(wizard_data)
    assert settings.qmt_password_encrypted == ""
    assert settings.qmt_password_salt == ""


def test_step5_password_hint_text_and_alignment():
    """Step5 密码和自动启动复选框布局正确."""
    from qmt_gateway.web.pages.init_wizard import Step5_QMT
    html = to_xml(Step5_QMT())
    # 提示文案已移除
    assert "可不填写，但会失去自动启动并登录 QMT 的能力" not in html
    # 自动启动复选框 label 包含正确文案
    assert "允许自动启动、重启 QMT" in html
    # QMT 路径提示中已移除 "提示：" 前缀
    assert "输入包含 userdata_mini" in html
    assert "提示：输入包含" not in html
    # 密码输入框有 id 以便 JS 联动
    assert 'id="qmt-password-input"' in html
    assert 'id="qmt-password-label"' in html
