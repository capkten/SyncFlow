from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Session

from backend.models.database import Base
from backend.utils.crypto import encrypt_secret


class SyncTaskSetting(Base):
    __tablename__ = "sync_task_settings"

    task_id = Column(Integer, ForeignKey("sync_tasks.id"), primary_key=True)
    mode = Column(String(20), default="one_way")
    poll_interval_seconds = Column(Integer, default=5)
    trash_dir = Column(String(100), default=".tongbu_trash")
    backup_dir = Column(String(100), default=".tongbu_backup")
    trash_retention_days = Column(Integer, default=7)
    backup_retention_days = Column(Integer, default=7)


class SyncEndpoint(Base):
    __tablename__ = "sync_endpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("sync_tasks.id"), index=True, nullable=False)
    side = Column(String(1), nullable=False)  # 端点标识 a/b
    type = Column(String(20), nullable=False)  # 端点类型 local/ssh
    path = Column(Text, nullable=False)
    host = Column(String(100))
    port = Column(Integer, default=22)
    username = Column(String(100))
    password = Column(String(200))
    ssh_key_path = Column(String(500))
    trash_dir = Column(String(100))
    backup_dir = Column(String(100))


class SyncFileState(Base):
    __tablename__ = "sync_file_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, index=True, nullable=False)
    rel_path = Column(Text, nullable=False)

    a_meta = Column(JSON, default=dict)
    b_meta = Column(JSON, default=dict)
    a_deleted = Column(Boolean, default=False)
    b_deleted = Column(Boolean, default=False)

    a_seen_at = Column(DateTime)
    b_seen_at = Column(DateTime)
    last_winner = Column(String(1))
    last_sync_at = Column(DateTime)

    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (UniqueConstraint("task_id", "rel_path", name="uix_task_path"),)


def get_task_settings(db: Session, task_id: int) -> Optional[SyncTaskSetting]:
    return db.query(SyncTaskSetting).filter(SyncTaskSetting.task_id == task_id).first()


def upsert_task_settings(db: Session, task_id: int, data: Dict) -> SyncTaskSetting:
    settings = get_task_settings(db, task_id)
    if not settings:
        settings = SyncTaskSetting(task_id=task_id)
        db.add(settings)
    for key, value in data.items():
        if value is not None:
            setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return settings


def get_endpoints(db: Session, task_id: int) -> Dict[str, SyncEndpoint]:
    rows = db.query(SyncEndpoint).filter(SyncEndpoint.task_id == task_id).all()
    return {row.side: row for row in rows}


def replace_endpoints(db: Session, task_id: int, endpoints: Dict[str, Dict]) -> Dict[str, SyncEndpoint]:
    db.query(SyncEndpoint).filter(SyncEndpoint.task_id == task_id).delete()
    db.commit()
    result = {}
    for side, data in endpoints.items():
        payload = dict(data)
        payload['password'] = encrypt_secret(payload.get('password'))
        endpoint = SyncEndpoint(task_id=task_id, side=side, **payload)
        db.add(endpoint)
        result[side] = endpoint
    db.commit()
    for side, endpoint in result.items():
        db.refresh(endpoint)
    return result


def get_all_file_states(db: Session, task_id: int) -> Dict[str, SyncFileState]:
    rows = db.query(SyncFileState).filter(SyncFileState.task_id == task_id).all()
    return {row.rel_path: row for row in rows}


def upsert_file_state(db: Session, task_id: int, rel_path: str, data: Dict) -> SyncFileState:
    state = db.query(SyncFileState).filter(
        SyncFileState.task_id == task_id,
        SyncFileState.rel_path == rel_path
    ).first()
    if not state:
        state = SyncFileState(task_id=task_id, rel_path=rel_path)
        db.add(state)
    for key, value in data.items():
        setattr(state, key, value)
    db.commit()
    db.refresh(state)
    return state
