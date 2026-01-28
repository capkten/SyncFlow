"""
日志查询 API
"""

from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from backend.models.database import get_db_session
from backend.models.sync_task import get_logs, get_log_stats, SyncLog
from backend.utils.auth import require_api_token

router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(require_api_token)])


# Pydantic 模型

class LogResponse(BaseModel):
    """日志响应"""
    id: int
    task_id: int
    event_type: str
    file_path: str
    dest_path: Optional[str]
    status: str
    error_message: Optional[str]
    sync_time: datetime
    
    class Config:
        from_attributes = True


class LogStatsResponse(BaseModel):
    """日志统计响应"""
    total: int
    success: int
    failed: int
    skipped: int


# API 路由

@router.get("/", response_model=List[LogResponse])
def list_logs(
    task_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db_session)
):
    """
    查询同步日志
    
    Args:
        task_id: 任务 ID（可选，不指定则查询所有任务）
        limit: 返回数量限制
        offset: 偏移量（分页）
        db: 数据库会话
    """
    logs = get_logs(db, task_id=task_id, limit=limit, offset=offset)
    return [LogResponse.from_orm(log) for log in logs]


@router.get("/stats", response_model=LogStatsResponse)
def get_stats(
    task_id: Optional[int] = None,
    db: Session = Depends(get_db_session)
):
    """
    获取日志统计信息
    
    Args:
        task_id: 任务 ID（可选）
        db: 数据库会话
    """
    stats = get_log_stats(db, task_id=task_id)
    
    return LogStatsResponse(
        total=sum(stats.values()),
        success=stats.get('success', 0),
        failed=stats.get('failed', 0),
        skipped=stats.get('skipped', 0)
    )
