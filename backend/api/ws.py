"""
WebSocket 实时接口
"""

from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.models.database import get_db
from backend.models.sync_task import get_all_tasks
from backend.core.task_manager import task_manager
from backend.utils.auth import verify_ws_token
from backend.utils.realtime import ws_hub

router = APIRouter()


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket, task_id: Optional[int] = None):
    if not await verify_ws_token(websocket):
        return
    await ws_hub.connect_logs(websocket, task_id=task_id)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_hub.disconnect(websocket)
    except Exception:
        ws_hub.disconnect(websocket)


@router.websocket("/ws/task-status")
async def ws_task_status(websocket: WebSocket):
    if not await verify_ws_token(websocket):
        return
    await ws_hub.connect_status(websocket)
    try:
        with get_db() as db:
            tasks = get_all_tasks(db)
            snapshot = [
                {
                    'task_id': t.id,
                    'name': t.name,
                    'enabled': t.enabled,
                    'is_running': t.id in task_manager.runners
                }
                for t in tasks
            ]
        await websocket.send_json({"type": "task_status_snapshot", "data": snapshot})
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_hub.disconnect(websocket)
    except Exception:
        ws_hub.disconnect(websocket)
