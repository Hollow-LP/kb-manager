"""密码哈希与 JWT 签发/校验。"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import get_settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except ValueError:
        # passlib 对超长/异常哈希抛出 ValueError
        return False


def create_access_token(user_id: int, extra: dict[str, Any] | None = None) -> tuple[str, int]:
    """返回 (token, 有效期秒数)。"""
    settings = get_settings()
    expire = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {"sub": str(user_id), "iat": now, "exp": now + expire, **(extra or {})}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), int(expire.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
