from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.events as events_module


@pytest.fixture(autouse=True)
def clear_subscribers():
    events_module._subscribers.clear()
    yield
    events_module._subscribers.clear()


@pytest.mark.asyncio
async def test_emit_calls_sync_handler():
    received = []
    events_module.subscribe("test-event", lambda payload: received.append(payload))
    await events_module.emit("test-event", {"key": "value"})
    assert len(received) == 1
    assert received[0]["key"] == "value"


@pytest.mark.asyncio
async def test_emit_calls_async_handler():
    received = []

    async def handler(payload):
        received.append(payload)

    events_module.subscribe("test-event", handler)
    await events_module.emit("test-event", {"key": "value"})
    assert len(received) == 1


@pytest.mark.asyncio
async def test_emit_swallows_handler_exception():
    def bad_handler(payload):
        raise ValueError("handler error")

    received = []
    events_module.subscribe("test-event", bad_handler)
    events_module.subscribe("test-event", lambda p: received.append(p))

    await events_module.emit("test-event", {"key": "value"})
    assert len(received) == 1


@pytest.mark.asyncio
async def test_emit_no_subscribers():
    await events_module.emit("unknown-event", {"key": "value"})


def test_subscribe():
    def handler(p: object) -> None:
        pass
    events_module.subscribe("my-event", handler)
    assert handler in events_module._subscribers["my-event"]


def test_setup_default_subscribers():
    with patch("core.events._ws_forwarder") as mock_fwd:
        mock_fwd.return_value = AsyncMock()
        events_module.setup_default_subscribers()
        assert len(events_module._subscribers) == 7


@pytest.mark.asyncio
async def test_ws_forwarder_calls_manager():
    mock_manager = MagicMock()
    mock_manager.send_to_all = AsyncMock()

    with patch.dict("sys.modules", {"routers.ws": MagicMock(manager=mock_manager)}):
        forwarder = events_module._ws_forwarder("bot-replied")
        await forwarder({"phone": "123"})

    mock_manager.send_to_all.assert_called_once()
    call_args = mock_manager.send_to_all.call_args[0][0]
    assert call_args["type"] == "bot-replied"
    assert call_args["phone"] == "123"
