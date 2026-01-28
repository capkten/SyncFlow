"""
同步任务和日志数据模型
"""

from datetime import datetime
from typing import List
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from backend.models.database import Base
from backend.utils.crypto import encrypt_secret
from backend.utils.realtime import ws_hub


class SyncTask(Base):
    """同步任务表"""
    __tablename__ = "sync_tasks"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    source_path = Column(Text, nullable=False)
    
    # 目标配置（JSON 格式存储）
    target_type = Column(String(20), nullable=False, default='local')  # local/ssh
    target_host = Column(String(100))
    target_port = Column(Integer, default=22)
    target_username = Column(String(100))
    target_password = Column(String(200))  # 自动加密存储（Fernet）
    target_ssh_key_path = Column(String(500))
    target_path = Column(Text, nullable=False)
    
    # 同步配置
    enabled = Column(Boolean, default=True)
    auto_start = Column(Boolean, default=True)
    eol_normalize = Column(String(10), default='lf')  # lf/crlf/keep
    exclude_patterns = Column(JSON, default=list)  # JSON 数组
    file_extensions = Column(JSON, default=list)  # JSON 数组
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关联日志
    logs = relationship("SyncLog", back_populates="task", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<SyncTask {self.name} ({self.source_path} -> {self.target_type}:{self.target_path})>"


class SyncLog(Base):
    """同步日志表"""
    __tablename__ = "sync_logs"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("sync_tasks.id"), nullable=False)
    
    event_type = Column(String(20), nullable=False)  # created/modified/deleted/moved
    file_path = Column(Text, nullable=False)
    dest_path = Column(Text)  # 用于 moved 事件
    
    status = Column(String(20), nullable=False)  # success/failed/skipped
    error_message = Column(Text)
    
    sync_time = Column(DateTime, default=datetime.now, index=True)
    
    # 关联任务
    task = relationship("SyncTask", back_populates="logs")
    
    def __repr__(self):
        return f"<SyncLog [{self.event_type}] {self.file_path} - {self.status}>"


# 数据库操作辅助函数

def create_task(db, task_data: dict) -> SyncTask:
    """创建同步任务"""
    if 'target_password' in task_data:
        task_data = dict(task_data)
        task_data['target_password'] = encrypt_secret(task_data.get('target_password'))
    task = SyncTask(**task_data)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db, task_id: int) -> SyncTask:
    """获取任务"""
    return db.query(SyncTask).filter(SyncTask.id == task_id).first()


def get_task_by_name(db, name: str) -> SyncTask:
    """根据名称获取任务"""
    return db.query(SyncTask).filter(SyncTask.name == name).first()


def get_all_tasks(db, enabled_only: bool = False) -> List[SyncTask]:
    """获取所有任务"""
    query = db.query(SyncTask)
    if enabled_only:
        query = query.filter(SyncTask.enabled == True)
    return query.all()


def update_task(db, task_id: int, task_data: dict) -> SyncTask:
    """更新任务"""
    task = get_task(db, task_id)
    if task:
        if 'target_password' in task_data:
            task_data = dict(task_data)
            task_data['target_password'] = encrypt_secret(task_data.get('target_password'))
        for key, value in task_data.items():
            setattr(task, key, value)
        task.updated_at = datetime.now()
        db.commit()
        db.refresh(task)
    return task


def delete_task(db, task_id: int) -> bool:
    """删除任务"""
    task = get_task(db, task_id)
    if task:
        db.delete(task)
        db.commit()
        return True
    return False


def create_log(db, log_data: dict) -> SyncLog:
    """创建同步日志"""
    log = SyncLog(**log_data)
    db.add(log)
    db.commit()
    db.refresh(log)
    ws_hub.publish_log({
        'id': log.id,
        'task_id': log.task_id,
        'event_type': log.event_type,
        'file_path': log.file_path,
        'dest_path': log.dest_path,
        'status': log.status,
        'error_message': log.error_message,
        'sync_time': log.sync_time.isoformat() if log.sync_time else None
    })
    return log


def get_logs(db, task_id: int = None, limit: int = 100, offset: int = 0) -> List[SyncLog]:
    """获取日志"""
    query = db.query(SyncLog)
    if task_id:
        query = query.filter(SyncLog.task_id == task_id)
    query = query.order_by(SyncLog.sync_time.desc())
    return query.offset(offset).limit(limit).all()


def get_log_stats(db, task_id: int = None) -> dict:
    """获取日志统计"""
    from sqlalchemy import func
    
    query = db.query(
        SyncLog.status,
        func.count(SyncLog.id).label('count')
    )
    
    if task_id:
        query = query.filter(SyncLog.task_id == task_id)
    
    query = query.group_by(SyncLog.status)
    
    results = query.all()
    return {status: count for status, count in results}
