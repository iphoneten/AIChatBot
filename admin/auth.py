"""admin-web 认证：argon2 密码哈希 + JWT（M5 完整接入）。"""

import jwt
from pwdlib import PasswordHash

_pwd_hasher = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    """生成 argon2 密码哈希。"""
    return _pwd_hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码。"""
    try:
        return _pwd_hasher.verify(plain, hashed)
    except Exception:  # noqa: BLE001 - 哈希格式非法时统一视为校验失败
        return False


def create_jwt(subject: str, secret: str, expires_hours: int = 12) -> str:
    """签发管理后台 JWT。"""
    from datetime import UTC, datetime, timedelta

    payload = {
        "sub": subject,
        "exp": datetime.now(UTC) + timedelta(hours=expires_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, secret: str) -> str | None:
    """校验 JWT，成功返回 subject。"""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return str(payload.get("sub"))
    except jwt.PyJWTError:
        return None
