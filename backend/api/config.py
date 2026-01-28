"""
配置管理 API
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional

from backend.config.settings import load_config, save_config, AppConfig, GlobalConfig
from backend.utils.auth import require_api_token

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(require_api_token)])


# Pydantic 模型

class GlobalConfigResponse(BaseModel):
    """全局配置响应"""
    log_level: str
    database_path: str
    web_host: str
    web_port: int
    api_token: Optional[str] = None
    ssh_host_key_policy: str
    ssh_known_hosts_path: str


class GlobalConfigUpdate(BaseModel):
    """全局配置更新"""
    log_level: str = None
    database_path: str = None
    web_host: str = None
    web_port: int = None
    api_token: Optional[str] = None
    ssh_host_key_policy: str = None
    ssh_known_hosts_path: str = None


# API 路由

@router.get("/global", response_model=GlobalConfigResponse)
def get_global_config():
    """获取全局配置"""
    try:
        config = load_config()
        return GlobalConfigResponse(
            log_level=config.global_.log_level,
            database_path=config.global_.database_path,
            web_host=config.global_.web_host,
            web_port=config.global_.web_port,
            api_token=config.global_.api_token,
            ssh_host_key_policy=config.global_.ssh_host_key_policy,
            ssh_known_hosts_path=config.global_.ssh_known_hosts_path
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载配置失败: {str(e)}")


@router.put("/global", response_model=GlobalConfigResponse)
def update_global_config(config_data: GlobalConfigUpdate):
    """更新全局配置"""
    try:
        config = load_config()
        
        # 更新配置
        if config_data.log_level is not None:
            config.global_.log_level = config_data.log_level
        if config_data.database_path is not None:
            config.global_.database_path = config_data.database_path
        if config_data.web_host is not None:
            config.global_.web_host = config_data.web_host
        if config_data.web_port is not None:
            config.global_.web_port = config_data.web_port
        if config_data.api_token is not None:
            config.global_.api_token = config_data.api_token
        if config_data.ssh_host_key_policy is not None:
            config.global_.ssh_host_key_policy = config_data.ssh_host_key_policy
        if config_data.ssh_known_hosts_path is not None:
            config.global_.ssh_known_hosts_path = config_data.ssh_known_hosts_path
        
        # 保存配置
        save_config(config)
        
        return GlobalConfigResponse(
            log_level=config.global_.log_level,
            database_path=config.global_.database_path,
            web_host=config.global_.web_host,
            web_port=config.global_.web_port,
            api_token=config.global_.api_token,
            ssh_host_key_policy=config.global_.ssh_host_key_policy,
            ssh_known_hosts_path=config.global_.ssh_known_hosts_path
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")
