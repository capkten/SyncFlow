"""
任务管理 API
"""

from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.models.database import get_db_session
from backend.models.sync_task import (
    SyncTask,
    create_task,
    get_task,
    get_all_tasks,
    update_task,
    delete_task
)
from backend.core.task_manager import task_manager
from backend.models.sync_state import get_task_settings, get_endpoints, upsert_task_settings, replace_endpoints
from backend.utils.auth import require_api_token

router = APIRouter(prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(require_api_token)])


# Pydantic 模型（API 请求/响应）

class EndpointConfig(BaseModel):
    """端点配置"""
    type: str
    path: str
    host: Optional[str] = None
    port: int = 22
    username: Optional[str] = None
    password: Optional[str] = None
    ssh_key_path: Optional[str] = None
    trash_dir: Optional[str] = None
    backup_dir: Optional[str] = None


class EndpointPublic(BaseModel):
    """端点响应"""
    type: str
    path: str
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    ssh_key_path: Optional[str] = None
    trash_dir: Optional[str] = None
    backup_dir: Optional[str] = None

class TaskCreate(BaseModel):
    """创建任务请求"""
    name: str
    mode: Optional[str] = 'one_way'
    source_path: str
    target_type: str = 'local'
    target_host: str = None
    target_port: int = 22
    target_username: str = None
    target_password: str = None
    target_ssh_key_path: str = None
    target_path: str
    enabled: bool = True
    auto_start: bool = True
    eol_normalize: str = 'lf'
    exclude_patterns: List[str] = []
    file_extensions: List[str] = []
    endpoints: Optional[Dict[str, EndpointConfig]] = None
    poll_interval_seconds: Optional[int] = None
    trash_dir: Optional[str] = None
    backup_dir: Optional[str] = None
    trash_retention_days: Optional[int] = None
    backup_retention_days: Optional[int] = None


class TaskUpdate(BaseModel):
    """更新任务请求"""
    name: str = None
    mode: Optional[str] = None
    source_path: str = None
    target_type: str = None
    target_host: str = None
    target_port: int = None
    target_username: str = None
    target_password: str = None
    target_ssh_key_path: str = None
    target_path: str = None
    enabled: bool = None
    auto_start: bool = None
    eol_normalize: str = None
    exclude_patterns: List[str] = None
    file_extensions: List[str] = None
    endpoints: Optional[Dict[str, EndpointConfig]] = None
    poll_interval_seconds: Optional[int] = None
    trash_dir: Optional[str] = None
    backup_dir: Optional[str] = None
    trash_retention_days: Optional[int] = None
    backup_retention_days: Optional[int] = None


class TaskResponse(BaseModel):
    """任务响应"""
    id: int
    name: str
    mode: str = 'one_way'
    source_path: str
    target_type: str
    target_host: str = None
    target_port: int = None
    target_username: str = None
    target_ssh_key_path: str = None
    target_path: str
    enabled: bool
    auto_start: bool
    eol_normalize: str
    exclude_patterns: List[str]
    file_extensions: List[str]
    is_running: bool = False
    endpoints: Optional[Dict[str, EndpointPublic]] = None
    poll_interval_seconds: Optional[int] = None
    trash_dir: Optional[str] = None
    backup_dir: Optional[str] = None
    trash_retention_days: Optional[int] = None
    backup_retention_days: Optional[int] = None
    
    class Config:
        from_attributes = True


def _build_task_response(db: Session, task: SyncTask) -> dict:
    """构建任务响应"""
    task_dict = TaskResponse.from_orm(task).model_dump()
    settings = get_task_settings(db, task.id)
    if settings:
        task_dict['mode'] = settings.mode
        task_dict['poll_interval_seconds'] = settings.poll_interval_seconds
        task_dict['trash_dir'] = settings.trash_dir
        task_dict['backup_dir'] = settings.backup_dir
        task_dict['trash_retention_days'] = settings.trash_retention_days
        task_dict['backup_retention_days'] = settings.backup_retention_days
    else:
        task_dict['mode'] = 'one_way'
    if task_dict.get('mode') == 'two_way':
        endpoints = get_endpoints(db, task.id)
        if endpoints:
            task_dict['endpoints'] = {
                side: {
                    'type': ep.type,
                    'path': ep.path,
                    'host': ep.host,
                    'port': ep.port,
                    'username': ep.username,
                    'ssh_key_path': ep.ssh_key_path,
                    'trash_dir': ep.trash_dir,
                    'backup_dir': ep.backup_dir
                }
                for side, ep in endpoints.items()
            }
    task_dict['is_running'] = task.id in task_manager.runners
    return task_dict


# API 路由

@router.get("/", response_model=List[TaskResponse])
def list_tasks(db: Session = Depends(get_db_session)):
    """获取所有任务列表"""
    tasks = get_all_tasks(db)
    return [_build_task_response(db, task) for task in tasks]


@router.get("/{task_id}", response_model=TaskResponse)
def get_task_detail(task_id: int, db: Session = Depends(get_db_session)):
    """获取任务详情"""
    task = get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _build_task_response(db, task)


@router.post("/", response_model=TaskResponse)
def create_new_task(task_data: TaskCreate, db: Session = Depends(get_db_session)):
    """创建新任务"""
    try:
        payload = task_data.model_dump()
        mode = payload.get('mode') or 'one_way'
        endpoints = payload.get('endpoints')
        if endpoints:
            mode = 'two_way'
        if mode == 'two_way':
            if not endpoints or 'a' not in endpoints or 'b' not in endpoints:
                raise HTTPException(status_code=400, detail="双向任务需要提供 endpoints.a 和 endpoints.b")
            ep_a = endpoints['a']
            ep_b = endpoints['b']
            payload['source_path'] = ep_a['path']
            payload['target_type'] = ep_b['type']
            payload['target_host'] = ep_b.get('host')
            payload['target_port'] = ep_b.get('port', 22)
            payload['target_username'] = ep_b.get('username')
            payload['target_password'] = ep_b.get('password')
            payload['target_ssh_key_path'] = ep_b.get('ssh_key_path')
            payload['target_path'] = ep_b['path']
        settings_data = {
            'mode': mode,
            'poll_interval_seconds': payload.get('poll_interval_seconds'),
            'trash_dir': payload.get('trash_dir'),
            'backup_dir': payload.get('backup_dir'),
            'trash_retention_days': payload.get('trash_retention_days'),
            'backup_retention_days': payload.get('backup_retention_days')
        }
        payload.pop('endpoints', None)
        payload.pop('poll_interval_seconds', None)
        payload.pop('trash_dir', None)
        payload.pop('backup_dir', None)
        payload.pop('trash_retention_days', None)
        payload.pop('backup_retention_days', None)
        payload.pop('mode', None)
        task = create_task(db, payload)
        upsert_task_settings(db, task.id, settings_data)
        if mode == 'two_way' and endpoints:
            replace_endpoints(db, task.id, endpoints)
        return TaskResponse.from_orm(task)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建任务失败: {str(e)}")


@router.put("/{task_id}", response_model=TaskResponse)
def update_existing_task(
    task_id: int,
    task_data: TaskUpdate,
    db: Session = Depends(get_db_session)
):
    """更新任务"""
    task = get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 如果任务正在运行，先停止
    if task_id in task_manager.runners:
        task_manager.stop_task(task_id)
    
    # 更新任务
    update_data = {k: v for k, v in task_data.model_dump().items() if v is not None}
    endpoints = update_data.get('endpoints')
    mode = update_data.get('mode')
    if endpoints:
        mode = 'two_way'
    if mode == 'two_way':
        if not endpoints or 'a' not in endpoints or 'b' not in endpoints:
            raise HTTPException(status_code=400, detail="双向任务需要提供 endpoints.a 和 endpoints.b")
        ep_a = endpoints['a']
        ep_b = endpoints['b']
        update_data['source_path'] = ep_a['path']
        update_data['target_type'] = ep_b['type']
        update_data['target_host'] = ep_b.get('host')
        update_data['target_port'] = ep_b.get('port', 22)
        update_data['target_username'] = ep_b.get('username')
        update_data['target_password'] = ep_b.get('password')
        update_data['target_ssh_key_path'] = ep_b.get('ssh_key_path')
        update_data['target_path'] = ep_b['path']
    settings_data = {
        'mode': mode,
        'poll_interval_seconds': update_data.get('poll_interval_seconds'),
        'trash_dir': update_data.get('trash_dir'),
        'backup_dir': update_data.get('backup_dir'),
        'trash_retention_days': update_data.get('trash_retention_days'),
        'backup_retention_days': update_data.get('backup_retention_days')
    }
    update_data.pop('endpoints', None)
    update_data.pop('poll_interval_seconds', None)
    update_data.pop('trash_dir', None)
    update_data.pop('backup_dir', None)
    update_data.pop('trash_retention_days', None)
    update_data.pop('backup_retention_days', None)
    update_data.pop('mode', None)
    updated_task = update_task(db, task_id, update_data)
    if mode:
        upsert_task_settings(db, task_id, settings_data)
    if endpoints and mode == 'two_way':
        replace_endpoints(db, task_id, endpoints)
    
    return TaskResponse.from_orm(updated_task)


@router.delete("/{task_id}")
def delete_existing_task(task_id: int, db: Session = Depends(get_db_session)):
    """删除任务"""
    # 如果任务正在运行，先停止
    if task_id in task_manager.runners:
        task_manager.stop_task(task_id)
    
    success = delete_task(db, task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return {"message": "任务已删除"}


@router.post("/{task_id}/start")
def start_task_endpoint(task_id: int, db: Session = Depends(get_db_session)):
    """启动任务"""
    try:
        task_manager.start_task(task_id)
        return {"message": "任务已启动", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"启动任务失败: {str(e)}")


@router.post("/{task_id}/stop")
def stop_task_endpoint(task_id: int):
    """停止任务"""
    try:
        task_manager.stop_task(task_id)
        return {"message": "任务已停止", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"停止任务失败: {str(e)}")


@router.post("/{task_id}/restart")
def restart_task_endpoint(task_id: int):
    """重启任务"""
    try:
        task_manager.restart_task(task_id)
        return {"message": "任务已重启", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"重启任务失败: {str(e)}")


@router.post("/{task_id}/sync")
def sync_task_all_endpoint(task_id: int, force: bool = False):
    """手动触发全量同步"""
    try:
        stats = task_manager.sync_task_all(task_id, force=force)
        return {
            "message": "全量同步完成",
            "task_id": task_id,
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"全量同步失败: {str(e)}")


@router.get("/{task_id}/status")
def get_task_status_endpoint(task_id: int):
    """获取任务状态"""
    status = task_manager.get_task_status(task_id)
    return status
