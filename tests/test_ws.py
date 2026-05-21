from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocket

from routers.ws import WebSocketConnectionManager, manager


@pytest.fixture(autouse=True)
def reset_manager():
    manager.active_connections.clear()
    yield
    manager.active_connections.clear()


def test_manager_initial_state():
    m = WebSocketConnectionManager()
    assert m.active_connections == []


@pytest.mark.asyncio
async def test_connect():
    m = WebSocketConnectionManager()
    ws = MagicMock(spec=WebSocket)
    await m.connect(ws)
    assert ws in m.active_connections


def test_disconnect():
    m = WebSocketConnectionManager()
    ws = MagicMock(spec=WebSocket)
    m.active_connections.append(ws)
    m.disconnect(ws)
    assert ws not in m.active_connections


def test_disconnect_not_in_list():
    m = WebSocketConnectionManager()
    ws = MagicMock(spec=WebSocket)
    m.disconnect(ws)
    assert ws not in m.active_connections


@pytest.mark.asyncio
async def test_send_to_all():
    m = WebSocketConnectionManager()
    ws1 = MagicMock(spec=WebSocket)
    ws1.send_json = AsyncMock()
    ws2 = MagicMock(spec=WebSocket)
    ws2.send_json = AsyncMock()
    m.active_connections = [ws1, ws2]

    await m.send_to_all({"type": "test"})

    ws1.send_json.assert_called_once_with({"type": "test"})
    ws2.send_json.assert_called_once_with({"type": "test"})


@pytest.mark.asyncio
async def test_send_to_all_removes_dead():
    m = WebSocketConnectionManager()
    ws1 = MagicMock(spec=WebSocket)
    ws1.send_json = AsyncMock()
    ws2 = MagicMock(spec=WebSocket)
    ws2.send_json = AsyncMock(side_effect=RuntimeError("broken"))
    m.active_connections = [ws1, ws2]

    await m.send_to_all({"type": "test"})

    assert ws1 in m.active_connections
    assert ws2 not in m.active_connections


@pytest.mark.asyncio
async def test_send_to_one():
    m = WebSocketConnectionManager()
    ws = MagicMock(spec=WebSocket)
    ws.send_json = AsyncMock()

    await m.send_to_one(ws, {"type": "pong"})

    ws.send_json.assert_called_once_with({"type": "pong"})


@pytest.mark.asyncio
async def test_send_to_one_dead():
    m = WebSocketConnectionManager()
    ws = MagicMock(spec=WebSocket)
    ws.send_json = AsyncMock(side_effect=RuntimeError("broken"))
    m.active_connections.append(ws)

    await m.send_to_one(ws, {"type": "pong"})

    assert ws not in m.active_connections


@pytest.mark.asyncio
async def test_send_to_all_no_connections():
    m = WebSocketConnectionManager()
    await m.send_to_all({"type": "test"})


@pytest.mark.asyncio
async def test_send_to_all_multiple_dead():
    m = WebSocketConnectionManager()
    ws1 = MagicMock(spec=WebSocket)
    ws1.send_json = AsyncMock(side_effect=RuntimeError("dead1"))
    ws2 = MagicMock(spec=WebSocket)
    ws2.send_json = AsyncMock(side_effect=RuntimeError("dead2"))
    ws3 = MagicMock(spec=WebSocket)
    ws3.send_json = AsyncMock()
    m.active_connections = [ws1, ws2, ws3]

    await m.send_to_all({"type": "test"})

    assert ws3 in m.active_connections
    assert ws1 not in m.active_connections
    assert ws2 not in m.active_connections


def test_disconnect_logs_count():
    m = WebSocketConnectionManager()
    ws1 = MagicMock(spec=WebSocket)
    ws2 = MagicMock(spec=WebSocket)
    m.active_connections = [ws1, ws2]

    m.disconnect(ws1)
    assert len(m.active_connections) == 1
    assert ws2 in m.active_connections


@pytest.mark.asyncio
async def test_connect_multiple():
    m = WebSocketConnectionManager()
    ws1 = MagicMock(spec=WebSocket)
    ws2 = MagicMock(spec=WebSocket)

    await m.connect(ws1)
    await m.connect(ws2)

    assert len(m.active_connections) == 2
