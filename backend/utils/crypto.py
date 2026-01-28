"""
敏感信息加解密工具
"""

import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from backend.utils.logger import logger


_SECRET_PREFIX = "enc:"
_ENV_KEY = "TONGBU_SECRET_KEY"
_FERNET = None


def _get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _get_key_path() -> Path:
    return _get_repo_root() / "data" / "secret.key"


def _load_or_create_key() -> bytes:
    env_key = os.getenv(_ENV_KEY)
    if env_key:
        key_bytes = env_key.encode("utf-8")
        try:
            Fernet(key_bytes)
            return key_bytes
        except Exception as e:
            logger.error(f"环境变量密钥无效: {e}")
            raise

    key_path = _get_key_path()
    if key_path.exists():
        return key_path.read_bytes().strip()

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    return key


def _get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_load_or_create_key())
    return _FERNET


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    if value.startswith(_SECRET_PREFIX):
        return value
    token = _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{_SECRET_PREFIX}{token}"


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    if not value.startswith(_SECRET_PREFIX):
        return value
    token = value[len(_SECRET_PREFIX):].encode("utf-8")
    try:
        return _get_fernet().decrypt(token).decode("utf-8")
    except InvalidToken as e:
        logger.error(f"密钥不匹配，无法解密: {e}")
        return None
