"""
日志工具模块 - 基于 loguru
"""

import sys
from pathlib import Path
from loguru import logger

# 移除默认处理器
logger.remove()

# 配置日志格式
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


def setup_logger(log_level: str = "INFO", log_dir: str = "./logs"):
    """
    配置日志系统
    
    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        log_dir: 日志文件目录
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # 控制台输出
    logger.add(
        sys.stdout,
        format=LOG_FORMAT,
        level=log_level,
        colorize=True
    )
    
    # 文件输出 - 所有日志
    logger.add(
        log_path / "file_sync_{time:YYYY-MM-DD}.log",
        format=LOG_FORMAT,
        level=log_level,
        rotation="00:00",  # 每天零点创建新文件
        retention="30 days",  # 保留30天
        encoding="utf-8"
    )
    
    # 文件输出 - 仅错误日志
    logger.add(
        log_path / "errors_{time:YYYY-MM-DD}.log",
        format=LOG_FORMAT,
        level="ERROR",
        rotation="00:00",
        retention="90 days",  # 错误日志保留更久
        encoding="utf-8"
    )
    
    logger.info(f"日志系统初始化完成，级别: {log_level}")


# 导出全局 logger
__all__ = ['logger', 'setup_logger']
