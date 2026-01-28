"""
WebSocket 实时推送
"""

import asyncio
import threading
from typing import Dict, Optional

from fastapi import WebSocket


class WebSocketHub:
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._log_clients: Dict[WebSocket, Optional[int]] = {}
        self._status_clients: Dict[WebSocket, bool] = {}
        self._lock = threading.Lock()

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect_logs(self, websocket: WebSocket, task_id: Optional[int] = None):
        await websocket.accept()
        with self._lock:
            self._log_clients[websocket] = task_id

    async def connect_status(self, websocket: WebSocket):
        await websocket.accept()
        with self._lock:
            self._status_clients[websocket] = True

    def disconnect(self, websocket: WebSocket):
        with self._lock:
            self._log_clients.pop(websocket, None)
            self._status_clients.pop(websocket, None)

    def publish_log(self, log_dict: dict):
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_log(log_dict), self._loop)

    def publish_task_status(self, status_dict: dict):
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_status(status_dict), self._loop)

    async def _broadcast_log(self, log_dict: dict):
        dead = []
        with self._lock:
            targets = list(self._log_clients.items())
        for ws, task_id in targets:
            if task_id and task_id != log_dict.get('task_id'):
                continue
            try:
                await ws.send_json({"type": "log", "data": log_dict})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def _broadcast_status(self, status_dict: dict):
        dead = []
        with self._lock:
            targets = list(self._status_clients.keys())
        for ws in targets:
            try:
                await ws.send_json({"type": "task_status", "data": status_dict})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_hub = WebSocketHub()
