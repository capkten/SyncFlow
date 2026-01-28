"""
API 认证工具
"""

import os
from typing import Optional

from fastapi import Header, HTTPException, WebSocket

from backend.config.settings import load_config


_ENV_TOKEN = "TONGBU_API_TOKEN"


def get_api_token() -> Optional[str]:
    env_token = os.getenv(_ENV_TOKEN)
    if env_token:
        return env_token
    config = load_config()
    return getattr(config.global_, "api_token", None)


def verify_bearer_token(authorization: Optional[str]) -> bool:
    token = get_api_token()
    if not token:
        return True
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        raise HTTPException(status_code=401, detail="无效的认证格式")
    if value != token:
        raise HTTPException(status_code=403, detail="认证失败")
    return True


def require_api_token(authorization: Optional[str] = Header(None)):
    return verify_bearer_token(authorization)


async def verify_ws_token(websocket: WebSocket) -> bool:
    token = get_api_token()
    if not token:
        return True
    query_token = websocket.query_params.get("token")
    header_token = websocket.headers.get("authorization")
    header_value = None
    if header_token:
        scheme, _, value = header_token.partition(" ")
        if scheme.lower() == "bearer":
            header_value = value
    if (query_token or header_value) != token:
        await websocket.close(code=1008)
        return False
    return True
