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
from starlette.testclient import TestClient

import qmt_gateway.apis.auth as auth_api
from qmt_gateway import app as app_module
from qmt_gateway.app import app
from qmt_gateway.db.models import Settings, User
from qmt_gateway.db.sqlite import db


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
    # 强制让 xtquant 测试失败：替换核心模块中的 require_xtdata
    from qmt_gateway import core as core_module

    def broken_require_xtdata(*args, **kwargs):
        raise RuntimeError("模拟 xtquant 不可用")

    monkeypatch.setattr(core_module, "require_xtdata", broken_require_xtdata)

    # 抓取提交前的状态
    settings_before = db.get_settings().to_dict()
    user_password_before = db.get_user("admin").password_hash

    # 提交一份"会破坏现状"的表单
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
            "principal": "2000000",
        },
    )

    # 应当返回连接失败页面（200 + 含"连接测试失败"），而不是重定向到 /
    assert response.status_code == 200
    body = response.text
    assert "QMT 连接失败" in body
    # 新版错误页应同时提示自动恢复失败原因，并给出"重试"/"返回修改配置"按钮
    assert "QMT 路径不存在" in body or "QMT 路径不正确" in body
    assert "重试" in body
    assert "返回修改配置" in body

    # 回滚：所有字段应与提交前一致
    settings_after = db.get_settings().to_dict()
    assert settings_after == settings_before
    assert bool(settings_after["init_completed"]) is True
    assert settings_after["server_port"] == 9999
    assert settings_after["qmt_account_id"] == "old-account"
    assert settings_after["qmt_path"] == r"C:\old\qmt"

    # 密码 hash 必须未变
    assert db.get_user("admin").password_hash == user_password_before
    # 旧密码仍可用
    assert auth_api.verify_password("old-pass-123", user_password_before)


def test_complete_rolls_back_settings_when_test_fails_after_partial_form(
    seeded_initialized_db, client, monkeypatch
):
    """即使 wizard_data 已被部分填入，xtquant 失败时 settings 必须保持原状。"""
    from qmt_gateway import core as core_module

    def broken_require_xtdata(*args, **kwargs):
        raise RuntimeError("xtquant unavailable")

    monkeypatch.setattr(core_module, "require_xtdata", broken_require_xtdata)

    # 先访问 step 路由写入内存数据
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
            "principal": "500000",
        },
    )
    assert response.status_code == 200
    assert "QMT 连接失败" in response.text

    # settings 应当完全没动
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
    """qmt_path 指向不存在的目录时，直接报\"路径不正确\"，不应尝试启动 QMT。"""
    from qmt_gateway import core as core_module

    def broken_require_xtdata(*args, **kwargs):
        raise RuntimeError("xtquant unavailable")

    monkeypatch.setattr(core_module, "require_xtdata", broken_require_xtdata)

    launch_called = {"value": False}

    def fake_launch(*args, **kwargs):
        launch_called["value"] = True
        return True

    from qmt_gateway import qmt_init_helpers

    monkeypatch.setattr(qmt_init_helpers, "launch_qmt_client", fake_launch)

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
            "principal": "2000000",
        },
    )
    assert response.status_code == 200
    body = response.text
    assert "QMT 连接失败" in body
    assert "QMT 路径不存在" in body
    # 不应触发启动
    assert launch_called["value"] is False
    # 提示用户返回修改
    assert "返回修改配置" in body
    # 回滚生效
    assert db.get_settings().to_dict() == settings_before


def test_recovery_attempts_launch_when_path_valid_but_qmt_not_running(
    seeded_initialized_db, client, monkeypatch, tmp_path
):
    """qmt_path 合法 + QMT 未运行 + 无交易密码 → wizard_complete 调用 restart_qmt 失败后返回等待对话框。

    新行为：wizard_complete 在连接测试失败后直接调用 _wizard_restart_qmt（复用
    trade_service.restart_qmt），若失败则返回含 auto_retry 的等待对话框。
    """
    from qmt_gateway import core as core_module

    userdata = _make_fake_qmt_install(tmp_path)

    def fake_require_xtdata(*args, **kwargs):
        raise RuntimeError("首次连接失败")

    monkeypatch.setattr(core_module, "require_xtdata", fake_require_xtdata)

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
    """QMT 未运行 + 有交易密码 → wizard_complete 调用 trade_service.restart_qmt 后成功。

    wizard_complete 在连接测试失败后调用 _wizard_restart_qmt（委托给
    trade_service.restart_qmt），启动成功后直接完成初始化并返回 302 重定向。
    """
    from qmt_gateway import core as core_module
    from qmt_gateway.services.trade_service import trade_service as ts_instance

    userdata = _make_fake_qmt_install(tmp_path)

    call_count = {"value": 0}

    def fake_require_xtdata(*args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise RuntimeError("首次连接失败")
        return _make_fake_xtdata()

    restart_called = {"value": False}

    def fake_restart_qmt(password):
        restart_called["value"] = True
        return {"success": True, "message": "QMT 已重启"}

    monkeypatch.setattr(core_module, "require_xtdata", fake_require_xtdata)
    monkeypatch.setattr(ts_instance, "restart_qmt", fake_restart_qmt)

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
            "principal": "3000000",
        },
        follow_redirects=False,
    )
    # trade_service.restart_qmt 应被调用
    assert restart_called["value"] is True
    # wizard_complete 应直接完成并重定向
    assert response.status_code in (302, 303)
    # 落盘生效
    saved = db.get_settings()
    assert bool(saved.init_completed) is True
    assert saved.server_port == 8888
    assert saved.qmt_account_id == "new-account"


def _make_fake_xtdata():
    """构造一个最小的 xtdata 桩，让 get_stock_list_in_sector 返回非空列表。"""

    class _FakeXtData:
        def get_stock_list_in_sector(self, sector):
            return ["000001.SZ", "600000.SH"]

    return _FakeXtData()
