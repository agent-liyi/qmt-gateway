"""对称加密工具，用于安全存储 QMT 交易密码。

使用 Fernet 对称加密 + PBKDF2 密钥派生：
- 用户登录密码作为密钥源
- 随机 salt 防止彩虹表攻击
- 加密后的密码 + salt 一起存储，解密时需要两者配合
"""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# PBKDF2 迭代次数（推荐值，平衡安全性和性能）
PBKDF2_ITERATIONS = 480_000
# Salt 长度（字节）
SALT_LENGTH = 16


def _derive_key(password: str, salt: bytes) -> bytes:
    """使用 PBKDF2 从密码派生 Fernet 密钥。

    Args:
        password: 用户密码（UTF-8 字符串）。
        salt: 随机 salt（bytes）。

    Returns:
        32 字节 base64 编码的 Fernet 密钥。
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    key = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


def encrypt_password(plaintext: str, key_password: str) -> tuple[str, str]:
    """使用对称加密加密密码。

    Args:
        plaintext: 要加密的明文（QMT 交易密码）。
        key_password: 用于派生加密密钥的密码（用户登录密码）。

    Returns:
        (encrypted_data, salt_hex) 元组：
        - encrypted_data: base64 编码的加密数据
        - salt_hex: hex 编码的 salt
    """
    if not plaintext:
        return ("", "")
    if not key_password:
        raise ValueError("加密密钥不能为空")

    salt = secrets.token_bytes(SALT_LENGTH)
    key = _derive_key(key_password, salt)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(plaintext.encode("utf-8"))

    return (encrypted.decode("ascii"), salt.hex())


def decrypt_password(encrypted_data: str, salt_hex: str, key_password: str) -> str:
    """解密密码。

    Args:
        encrypted_data: base64 编码的加密数据。
        salt_hex: hex 编码的 salt。
        key_password: 用于派生加密密钥的密码（用户登录密码）。

    Returns:
        解密后的明文密码。

    Raises:
        ValueError: 如果数据为空或解密失败（密码错误或数据损坏）。
    """
    if not encrypted_data or not salt_hex:
        return ""
    if not key_password:
        raise ValueError("解密密钥不能为空")

    try:
        salt = bytes.fromhex(salt_hex)
        key = _derive_key(key_password, salt)
        fernet = Fernet(key)
        decrypted = fernet.decrypt(encrypted_data.encode("ascii"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        raise ValueError("解密失败：密钥不正确或数据已损坏")
    except Exception as exc:
        raise ValueError(f"解密失败：{exc}") from exc


def is_encrypted_password_set(encrypted_data: str, salt_hex: str) -> bool:
    """判断是否已设置加密密码。"""
    return bool(encrypted_data and salt_hex)


def decrypt_password_with_key(encrypted_data: str, derived_key_b64: str) -> str:
    """使用预派生的密钥解密密码。

    适用于 session 中已存储派生密钥的场景，无需再次执行 PBKDF2。

    Args:
        encrypted_data: base64 编码的加密数据。
        derived_key_b64: base64 编码的派生密钥（如 session 中存储的 qmt_decrypt_key）。

    Returns:
        解密后的明文密码。

    Raises:
        ValueError: 如果数据为空或解密失败。
    """
    if not encrypted_data:
        return ""
    if not derived_key_b64:
        raise ValueError("派生密钥不能为空")

    try:
        fernet = Fernet(derived_key_b64.encode("ascii"))
        decrypted = fernet.decrypt(encrypted_data.encode("ascii"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        raise ValueError("解密失败：密钥不正确或数据已损坏")
    except Exception as exc:
        raise ValueError(f"解密失败：{exc}") from exc


def _get_machine_key() -> bytes:
    """获取当前机器的唯一标识作为加密密钥源。

    组合多个机器特征：机器名 + 用户名 + 可执行文件路径，
    生成一个与运行环境绑定的密钥种子。这样即使数据库被复制到其他机器，
    仍然无法解密 auto-start 密码。
    """
    import hashlib
    import platform
    import sys

    parts = [
        platform.node() or "",
        os.environ.get("USERNAME", os.environ.get("USER", "")),
        sys.executable,
        os.path.splitdrive(sys.executable)[0] or "C:",
    ]
    seed = "\n".join(parts)
    return hashlib.sha256(seed.encode("utf-8")).digest()


def encrypt_for_auto_start(plaintext: str) -> str:
    """使用机器密钥加密密码，用于进程启动时自动解密。

    安全性说明：此加密依赖本机环境特征，安全性低于用户密码派生的加密。
    仅在用户明确启用 auto_start_qmt 时使用，且应与用户密码加密互为补充。

    Args:
        plaintext: 要加密的明文密码。

    Returns:
        base64 编码的加密字符串，内含 salt + ciphertext。
    """
    if not plaintext:
        return ""

    machine_key = _get_machine_key()
    salt = secrets.token_bytes(SALT_LENGTH)
    combined = machine_key + salt
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=combined,
        iterations=PBKDF2_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(machine_key))
    fernet = Fernet(key)
    encrypted = fernet.encrypt(plaintext.encode("utf-8"))

    payload = salt + encrypted
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_for_auto_start(encrypted_payload: str) -> str:
    """使用机器密钥解密 auto-start 密码。

    Args:
        encrypted_payload: encrypt_for_auto_start 返回的加密字符串。

    Returns:
        解密后的明文密码。

    Raises:
        ValueError: 如果数据为空或解密失败。
    """
    if not encrypted_payload:
        return ""

    try:
        payload = base64.urlsafe_b64decode(encrypted_payload.encode("ascii"))
        salt = payload[:SALT_LENGTH]
        encrypted = payload[SALT_LENGTH:]

        machine_key = _get_machine_key()
        combined = machine_key + salt
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=combined,
            iterations=PBKDF2_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_key))
        fernet = Fernet(key)
        decrypted = fernet.decrypt(encrypted)
        return decrypted.decode("utf-8")
    except InvalidToken:
        raise ValueError("auto-start 密码解密失败：机器环境可能已变更")
    except Exception as exc:
        raise ValueError(f"auto-start 密码解密失败：{exc}") from exc
