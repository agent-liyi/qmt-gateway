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
