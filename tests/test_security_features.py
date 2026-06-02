"""API key 管理与鉴权回归测试。"""

import hashlib
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import qmt_gateway.apis.auth as auth_api
from qmt_gateway.app import app
from qmt_gateway.db.models import User
from qmt_gateway.db.sqlite import db


@pytest.fixture
def in_memory_db(monkeypatch):
    """用临时文件数据库替换默认数据库，避免污染真实数据。"""
    tmp_dir = tempfile.mkdtemp(prefix="qmt-apikey-test-")
    db_path = Path(tmp_dir) / "test.db"
    db.init(db_path)
    yield db_path


@pytest.fixture
def seeded_admin(in_memory_db):
    """向临时数据库插入一个 admin 用户用于鉴权。"""
    admin = User(username="admin", password_hash=auth_api.hash_password("old-pass-123"))
    db.save_user(admin)
    return admin


@pytest.fixture
def client():
    return TestClient(app)


def _login_session(
    client: TestClient,
    username: str = "admin",
    password: str = "old-pass-123",
):
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303), response.text
    return response


def test_generate_api_key_returns_plaintext_once(seeded_admin, client):
    _login_session(client)

    response = client.post("/api/api-keys", data={"name": "tester"})
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    plaintext = body["data"]["plaintext"]
    assert plaintext.startswith("qmt_")
    assert len(plaintext) > 20
    assert body["data"]["key_prefix"].startswith("qmt_")
    assert len(body["data"]["key_prefix"]) == 12

    # 同一 hash 已写入数据库
    key_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    record = db.get_api_key_by_hash(key_hash)
    assert record is not None
    assert record.key_prefix == body["data"]["key_prefix"]


def test_generate_api_key_requires_session(seeded_admin, client):
    response = client.post("/api/api-keys", data={"name": "no-session"})
    assert response.status_code == 401
    assert "未登录" in response.text or "API key" in response.text


def test_list_api_keys_returns_only_metadata(seeded_admin, client):
    _login_session(client)
    client.post("/api/api-keys", data={"name": "alpha"})
    client.post("/api/api-keys", data={"name": "beta"})

    response = client.get("/api/api-keys")
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 2
    for entry in data:
        assert "plaintext" not in entry
        assert "key_hash" not in entry
        assert entry["revoked"] is False
        assert entry["key_prefix"].startswith("qmt_")


def test_revoke_api_key_disables_lookup(seeded_admin, client):
    _login_session(client)
    body = client.post("/api/api-keys", data={"name": "to-revoke"}).json()
    key_id = body["data"]["id"]
    plaintext = body["data"]["plaintext"]

    response = client.delete(f"/api/api-keys/{key_id}")
    assert response.status_code == 200

    # 已吊销的 key 不再可用于校验
    key_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    record = db.get_api_key_by_hash(key_hash)
    assert record is None


def test_require_api_key_or_session_accepts_x_api_key_header(seeded_admin, client):
    _login_session(client)
    body = client.post("/api/api-keys", data={"name": "header-test"}).json()
    plaintext = body["data"]["plaintext"]

    response = client.get(
        "/api/api-keys",
        headers={"X-API-Key": plaintext, "Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 0


def test_require_api_key_or_session_rejects_bad_key(seeded_admin, client):
    response = client.get(
        "/api/api-keys",
        headers={"X-API-Key": "qmt_does-not-exist", "Accept": "application/json"},
    )
    assert response.status_code == 401


def test_require_api_key_or_session_rejects_when_no_credentials(seeded_admin, client):
    response = client.get("/api/api-keys", headers={"Accept": "application/json"})
    assert response.status_code == 401


def test_x_api_key_works_on_programmatic_trade_endpoint(seeded_admin, client):
    _login_session(client)
    body = client.post("/api/api-keys", data={"name": "trade-test"}).json()
    plaintext = body["data"]["plaintext"]

    response = client.get(
        "/api/trade/asset",
        headers={"X-API-Key": plaintext, "Accept": "application/json"},
    )
    assert response.status_code == 200


def test_change_password_clears_session_and_updates_hash(seeded_admin, client):
    _login_session(client)
    response = client.post(
        "/auth/password",
        data={
            "old_password": "old-pass-123",
            "new_password": "new-pass-456",
            "new_password_confirm": "new-pass-456",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    # 数据库中密码已更新
    refreshed = db.get_user("admin")
    assert auth_api.verify_password("new-pass-456", refreshed.password_hash)
    assert not auth_api.verify_password("old-pass-123", refreshed.password_hash)

    # 会话已被清空 → 再次访问受保护端点应 401
    after = client.get("/api/api-keys", headers={"Accept": "application/json"})
    assert after.status_code == 401


def test_change_password_rejects_mismatched_confirm(seeded_admin, client):
    _login_session(client)
    response = client.post(
        "/auth/password",
        data={
            "old_password": "old-pass-123",
            "new_password": "new-pass-456",
            "new_password_confirm": "different",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "不一致" in response.json()["message"]


def test_change_password_rejects_wrong_old_password(seeded_admin, client):
    _login_session(client)
    response = client.post(
        "/auth/password",
        data={
            "old_password": "wrong-old",
            "new_password": "new-pass-456",
            "new_password_confirm": "new-pass-456",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "原密码" in response.json()["message"]


def test_change_password_requires_session(seeded_admin, client):
    response = client.post(
        "/auth/password",
        data={
            "old_password": "old-pass-123",
            "new_password": "new-pass-456",
            "new_password_confirm": "new-pass-456",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is False


def test_main_layout_includes_security_menu_items(seeded_admin):
    """确认主布局中包含新增的菜单项与 modal。"""
    from fastcore.xml import to_xml

    from qmt_gateway.web.layouts.main import MainLayout

    layout = MainLayout("x", user={"username": "admin"}, active_menu="trading")
    html = str(to_xml(layout))
    assert "showChangePasswordModal" in html
    assert "showApiKeyModal" in html
    assert "修改密码" in html
    assert "管理 API key" in html
    assert "change-password-modal" in html
    assert "api-key-modal" in html
    assert "/auth/password" in html
    assert "/api/api-keys" in html
