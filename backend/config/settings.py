"""
配置管理模块
"""

from pathlib import Path
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
import yaml


class TargetConfig(BaseModel):
    """目标端配置"""
    type: Literal['local', 'ssh'] = 'local'
    host: Optional[str] = None
    port: int = 22
    username: Optional[str] = None
    password: Optional[str] = None
    ssh_key_path: Optional[str] = None
    path: str


class SyncTaskConfig(BaseModel):
    """单个同步任务配置"""
    name: str
    source_path: str
    target: TargetConfig
    enabled: bool = True
    auto_start: bool = True
    eol_normalize: Literal['lf', 'crlf', 'keep'] = 'lf'
    exclude_patterns: List[str] = Field(default_factory=list)
    file_extensions: List[str] = Field(default_factory=list)


class GlobalConfig(BaseModel):
    """全局配置"""
    log_level: str = 'INFO'
    database_path: str = './data/sync.db'
    web_host: str = '0.0.0.0'
    web_port: int = 8888
    api_token: Optional[str] = None
    ssh_host_key_policy: Literal['auto', 'reject', 'warning'] = 'reject'
    ssh_known_hosts_path: str = './data/known_hosts'


class AppConfig(BaseModel):
    """应用配置"""
    global_: GlobalConfig = Field(default_factory=GlobalConfig, alias='global')
    sync_tasks: List[SyncTaskConfig] = Field(default_factory=list)
    
    class Config:
        populate_by_name = True


def load_config(config_file: str = 'config.yaml') -> AppConfig:
    """
    加载配置文件
    
    Args:
        config_file: 配置文件路径
        
    Returns:
        AppConfig 对象
    """
    config_path = Path(config_file)
    
    if not config_path.exists():
        # 如果配置文件不存在，返回默认配置
        return AppConfig(global_=GlobalConfig(), sync_tasks=[])
    
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    return AppConfig(**data)


def save_config(config: AppConfig, config_file: str = 'config.yaml'):
    """
    保存配置到文件
    
    Args:
        config: AppConfig 对象
        config_file: 配置文件路径
    """
    config_path = Path(config_file)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 转换为字典并处理 alias
    data = {
        'global': config.global_.model_dump(),
        'sync_tasks': [task.model_dump() for task in config.sync_tasks]
    }
    
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


if __name__ == '__main__':
    # 测试加载配置
    config = load_config('config.example.yaml')
    print(f"加载了 {len(config.sync_tasks)} 个同步任务")
    for task in config.sync_tasks:
        print(f"  - {task.name}: {task.source_path} -> {task.target.type}")
