import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.background as bg


@pytest.fixture(autouse=True)
def reset_state():
    bg._phone_lock_last_used.clear()
    if bg._cleanup_task and not bg._cleanup_task.done():
        bg._cleanup_task.cancel()
    bg._cleanup_task = None
    yield
    bg._phone_lock_last_used.clear()


def test_touch_phone_lock():
    bg.touch_phone_lock("56912345678")
    assert "56912345678" in bg._phone_lock_last_used
    assert bg._phone_lock_last_used["56912345678"] > 0


def test_prune_phone_locks_removes_stale():
    import core.hitl_router as hitl_mod

    mock_locks = {"56911111111": asyncio.Lock(), "56922222222": asyncio.Lock()}
    now = time.monotonic()
    bg._phone_lock_last_used["56911111111"] = now - 4000
    bg._phone_lock_last_used["56922222222"] = now

    original = getattr(hitl_mod, "_phone_locks", None)
    hitl_mod._phone_locks = mock_locks
    try:
        bg.prune_phone_locks()
    finally:
        if original is not None:
            hitl_mod._phone_locks = original
        else:
            delattr(hitl_mod, "_phone_locks")

    assert "56911111111" not in bg._phone_lock_last_used
    assert "56922222222" in bg._phone_lock_last_used
    assert "56911111111" not in mock_locks
    assert "56922222222" in mock_locks


def test_prune_phone_locks_none_stale():
    import core.hitl_router as hitl_mod

    now = time.monotonic()
    bg._phone_lock_last_used["56933333333"] = now
    mock_locks = {"56933333333": asyncio.Lock()}

    original = getattr(hitl_mod, "_phone_locks", None)
    hitl_mod._phone_locks = mock_locks
    try:
        bg.prune_phone_locks()
    finally:
        if original is not None:
            hitl_mod._phone_locks = original
        else:
            delattr(hitl_mod, "_phone_locks")

    assert "56933333333" in bg._phone_lock_last_used


def test_start_cleanup_task():
    with patch("core.background.asyncio.create_task") as mock_create:
        mock_create.return_value = MagicMock(done=MagicMock(return_value=True))
        bg.start_cleanup_task()
        mock_create.assert_called_once()


def test_stop_cleanup_task():
    mock_task = MagicMock()
    mock_task.done.return_value = False
    bg._cleanup_task = mock_task

    bg.stop_cleanup_task()
    mock_task.cancel.assert_called_once()


def test_stop_cleanup_task_already_done():
    mock_task = MagicMock()
    mock_task.done.return_value = True
    bg._cleanup_task = mock_task

    bg.stop_cleanup_task()
    mock_task.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_loop_iteration():
    call_count = 0

    async def fake_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    import core.metrics as metrics_mod

    mock_refresh_conv = AsyncMock()
    mock_refresh_sess = AsyncMock()
    original_conv = getattr(metrics_mod, "refresh_active_conversations", None)
    original_sess = getattr(metrics_mod, "refresh_active_sessions", None)
    metrics_mod.refresh_active_conversations = mock_refresh_conv
    metrics_mod.refresh_active_sessions = mock_refresh_sess

    import core.hitl_router as hitl_mod
    original_locks = getattr(hitl_mod, "_phone_locks", None)
    hitl_mod._phone_locks = {}

    try:
        with patch("core.background.asyncio.sleep", side_effect=fake_sleep), \
             patch("core.background.rate_limiter") as mock_rl, \
             patch("core.background.api_rate_limiter") as mock_api_rl:
            mock_rl.cleanup = MagicMock()
            mock_api_rl.cleanup = MagicMock()
            import contextlib
            with contextlib.suppress(asyncio.CancelledError):
                await bg._cleanup_loop()
    finally:
        if original_conv is not None:
            metrics_mod.refresh_active_conversations = original_conv
        else:
            delattr(metrics_mod, "refresh_active_conversations")
        if original_sess is not None:
            metrics_mod.refresh_active_sessions = original_sess
        else:
            delattr(metrics_mod, "refresh_active_sessions")
        if original_locks is not None:
            hitl_mod._phone_locks = original_locks
        else:
            delattr(hitl_mod, "_phone_locks")

    mock_rl.cleanup.assert_called()
