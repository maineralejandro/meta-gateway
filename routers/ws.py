from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import List
from core.config import settings
import structlog

logger = structlog.get_logger()
router = APIRouter()


class WebSocketConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("ws_connected", total=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("ws_disconnected", total=len(self.active_connections))

    async def send_to_all(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for c in dead:
            self.disconnect(c)

    async def send_to_one(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)


manager = WebSocketConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
    if settings.DASHBOARD_TOKEN and token != settings.DASHBOARD_TOKEN:
        await websocket.close(code=4001, reason="Invalid token")
        return
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await manager.send_to_one(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
