import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.config import settings

logger = structlog.get_logger()
router = APIRouter()


class WebSocketConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("ws_connected", total=len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("ws_disconnected", total=len(self.active_connections))

    async def send_to_all(self, message: dict[str, Any]) -> None:
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                logger.debug("ws_send_all_failed", total=len(self.active_connections))
                dead.append(connection)
        for c in dead:
            self.disconnect(c)

    async def send_to_one(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        try:
            await websocket.send_json(message)
        except Exception:
            logger.debug("ws_send_one_failed")
            self.disconnect(websocket)


manager = WebSocketConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    if settings.DASHBOARD_TOKEN:
        query_token = websocket.query_params.get("token")
        if query_token == settings.DASHBOARD_TOKEN:
            await websocket.send_json({"type": "auth_ok"})
        else:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=5)
            except TimeoutError:
                await websocket.close(code=4001, reason="Auth timeout")
                return
            except WebSocketDisconnect:
                return
            if data.get("type") != "auth" or data.get("token") != settings.DASHBOARD_TOKEN:
                await websocket.close(code=4001, reason="Invalid token")
                return
            await websocket.send_json({"type": "auth_ok"})
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await manager.send_to_one(websocket, {"type": "pong"})
        except WebSocketDisconnect:
            manager.disconnect(websocket)
