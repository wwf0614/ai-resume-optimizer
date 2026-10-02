"""用户认证：密码哈希（PBKDF2-SHA256）与登录令牌生成。"""
import hashlib
import hmac
import secrets

_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    """生成带随机盐的密码哈希，格式：salt$digest（十六进制）。"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS
    )
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码；stored 格式异常时一律返回 False。"""
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS
    )
    return hmac.compare_digest(dk.hex(), expected)


def new_token() -> str:
    """生成 64 位十六进制登录令牌。"""
    return secrets.token_hex(32)
