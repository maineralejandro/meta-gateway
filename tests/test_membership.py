from unittest.mock import AsyncMock, patch

import pytest

from core.capabilities.membership import (
    MEMBERSHIP_CANCEL_RE,
    MEMBERSHIP_CHECK_RE,
    MEMBERSHIP_PLAN_RE,
    MEMBERSHIP_TRIAL_RE,
    MembershipCapability,
)


@pytest.fixture
def mem():
    inst = MembershipCapability()
    inst._ensure_loaded = AsyncMock()
    inst._persist_membership = AsyncMock()
    inst._cancel_membership_db = AsyncMock()
    return inst


def test_membership_plan_re_matches():
    m = MEMBERSHIP_PLAN_RE.search("text [MEMBERSHIP_PLAN:premium] more")
    assert m is not None
    assert m.group(1) == "premium"


def test_membership_check_re_matches():
    assert MEMBERSHIP_CHECK_RE.search("[MEMBERSHIP_CHECK]") is not None


def test_membership_cancel_re_matches():
    assert MEMBERSHIP_CANCEL_RE.search("[MEMBERSHIP_CANCEL]") is not None


def test_membership_trial_re_matches():
    m = MEMBERSHIP_TRIAL_RE.search("text [MEMBERSHIP_TRIAL:premium] more")
    assert m is not None
    assert m.group(1) == "premium"


@pytest.mark.asyncio
async def test_activate_plan(mem):
    await mem.activate_plan("+56910000001", "premium")
    m = await mem.get_membership("+56910000001")
    assert m is not None
    assert m["plan_key"] == "premium"
    assert m["status"] == "active"


@pytest.mark.asyncio
async def test_cancel_membership(mem):
    await mem.activate_plan("+56910000001", "premium")
    await mem.cancel_membership("+56910000001")
    m = await mem.get_membership("+56910000001")
    assert m is not None
    assert m["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_nonexistent_membership(mem):
    await mem.cancel_membership("+56910000001")
    m = await mem.get_membership("+56910000001")
    assert m is None


@pytest.mark.asyncio
async def test_parse_tags_plan(mem):
    text = "Bienvenido al plan [MEMBERSHIP_PLAN:premium]"
    cleaned = await mem.parse_tags("+56910000001", text, {})
    assert "[MEMBERSHIP_PLAN" not in cleaned
    m = await mem.get_membership("+56910000001")
    assert m is not None
    assert m["plan_key"] == "premium"


@pytest.mark.asyncio
async def test_parse_tags_cancel(mem):
    await mem.activate_plan("+56910000001", "premium")
    text = "Membresia cancelada [MEMBERSHIP_CANCEL]"
    cleaned = await mem.parse_tags("+56910000001", text, {})
    assert "[MEMBERSHIP_CANCEL" not in cleaned
    m = await mem.get_membership("+56910000001")
    assert m["status"] == "cancelled"


@pytest.mark.asyncio
async def test_parse_tags_check_stripped(mem):
    text = "Consultando [MEMBERSHIP_CHECK]"
    cleaned = await mem.parse_tags("+56910000001", text, {})
    assert "[MEMBERSHIP_CHECK" not in cleaned


@pytest.mark.asyncio
async def test_format_for_context_no_membership(mem):
    result = await mem.format_for_context("+56910000001", {})
    assert result is None


@pytest.mark.asyncio
async def test_format_for_context_with_membership(mem):
    await mem.activate_plan("+56910000001", "premium")
    result = await mem.format_for_context("+56910000001", {})
    assert result is not None
    assert "Premium" in result
    assert "30,000" in result
    assert "Activa" in result


@pytest.mark.asyncio
async def test_format_for_context_with_trial(mem):
    mem.config = {"allow_free_trial": True, "trial_days": 7}
    await mem.activate_trial("+56910000001", "premium")
    result = await mem.format_for_context("+56910000001", {})
    assert result is not None
    assert "Prueba gratis" in result
    assert "30,000" in result


@pytest.mark.asyncio
async def test_format_for_context_cancelled(mem):
    await mem.activate_plan("+56910000001", "premium")
    await mem.cancel_membership("+56910000001")
    result = await mem.format_for_context("+56910000001", {})
    assert result is None


@pytest.mark.asyncio
async def test_clear(mem):
    await mem.activate_plan("+56910000001", "premium")
    await mem.clear("+56910000001", {})
    m = await mem.get_membership("+56910000001")
    assert m is None


def test_get_prompt_instructions():
    inst = MembershipCapability()
    instructions = inst.get_prompt_instructions({})
    assert "MEMBERSHIP_PLAN" in instructions
    assert "premium" in instructions
    assert "MEMBERSHIP_TRIAL" not in instructions


def test_get_prompt_instructions_with_trial():
    inst = MembershipCapability(config={"allow_free_trial": True, "trial_days": 7})
    instructions = inst.get_prompt_instructions({})
    assert "MEMBERSHIP_TRIAL" in instructions
    assert "7" in instructions


def test_get_plans():
    inst = MembershipCapability()
    plans = inst.get_plans()
    assert len(plans) == 3
    keys = [p["key"] for p in plans]
    assert "basico" in keys
    assert "premium" in keys
    assert "anual" in keys


def test_next_billing_date_monthly():
    inst = MembershipCapability()
    result = inst._next_billing_date("premium", "2025-01-15")
    assert result == "2025-02-14"


def test_next_billing_date_yearly():
    inst = MembershipCapability()
    result = inst._next_billing_date("anual", "2025-01-15")
    assert result == "2026-01-15"


@pytest.mark.asyncio
async def test_ensure_loaded_logs_error_on_db_failure():
    inst = MembershipCapability()
    with patch("db.database.get_db", side_effect=RuntimeError("db down")):
        await inst._ensure_loaded("+56910000001")
        assert inst._memberships.get("+56910000001") is None


@pytest.mark.asyncio
async def test_activate_trial_success(mem):
    mem.config = {"allow_free_trial": True, "trial_days": 7}
    await mem.activate_trial("+56910000001", "premium")
    m = await mem.get_membership("+56910000001")
    assert m is not None
    assert m["status"] == "trial"
    assert m["plan_key"] == "premium"


@pytest.mark.asyncio
async def test_activate_trial_not_allowed(mem):
    mem.config = {"allow_free_trial": False}
    await mem.activate_trial("+56910000001", "premium")
    m = await mem.get_membership("+56910000001")
    assert m is None


@pytest.mark.asyncio
async def test_activate_trial_already_active(mem):
    mem.config = {"allow_free_trial": True, "trial_days": 7}
    await mem.activate_plan("+56910000001", "premium")
    await mem.activate_trial("+56910000001", "premium")
    m = await mem.get_membership("+56910000001")
    assert m["status"] == "active"


@pytest.mark.asyncio
async def test_parse_tags_trial(mem):
    mem.config = {"allow_free_trial": True, "trial_days": 7}
    text = "Prueba gratis activada [MEMBERSHIP_TRIAL:premium]"
    cleaned = await mem.parse_tags("+56910000001", text, {})
    assert "[MEMBERSHIP_TRIAL" not in cleaned
    m = await mem.get_membership("+56910000001")
    assert m is not None
    assert m["status"] == "trial"


@pytest.mark.asyncio
async def test_cancel_trial(mem):
    mem.config = {"allow_free_trial": True, "trial_days": 7}
    await mem.activate_trial("+56910000001", "premium")
    await mem.cancel_membership("+56910000001")
    m = await mem.get_membership("+56910000001")
    assert m["status"] == "cancelled"


def test_get_tool_definitions():
    inst = MembershipCapability()
    defs = inst.get_tool_definitions({})
    assert len(defs) == 5
    names = [d["function"]["name"] for d in defs]
    assert "membership_activate" in names
    assert "membership_cancel" in names
    assert "membership_trial" in names
    assert "membership_check" in names
    assert "membership_get_plans" in names


def test_get_tool_names():
    inst = MembershipCapability()
    names = inst.get_tool_names()
    assert names == {"membership_activate", "membership_cancel", "membership_trial", "membership_check", "membership_get_plans"}


@pytest.mark.asyncio
async def test_execute_activate(mem):
    result = await mem.execute_tool("membership_activate", {"plan_key": "premium"}, "+56910000001", "tc1", {})
    assert result["success"] is True
    assert result["action"] == "membership_activated"
    assert result["membership_state"]["plan_key"] == "premium"


@pytest.mark.asyncio
async def test_execute_activate_invalid_plan(mem):
    result = await mem.execute_tool("membership_activate", {"plan_key": "nonexistent"}, "+56910000001", "tc2", {})
    assert result["success"] is False
    assert "valid_plan_keys" in result
    assert "instruction" in result


@pytest.mark.asyncio
async def test_execute_cancel(mem):
    await mem.activate_plan("+56910000001", "premium")
    result = await mem.execute_tool("membership_cancel", {}, "+56910000001", "tc3", {})
    assert result["success"] is True
    assert result["action"] == "membership_cancelled"


@pytest.mark.asyncio
async def test_execute_cancel_no_active(mem):
    result = await mem.execute_tool("membership_cancel", {}, "+56910000001", "tc4", {})
    assert result["success"] is False
    assert "No active membership" in result["error"]


@pytest.mark.asyncio
async def test_execute_trial(mem):
    mem.config = {"allow_free_trial": True, "trial_days": 7}
    result = await mem.execute_tool("membership_trial", {"plan_key": "premium"}, "+56910000001", "tc5", {})
    assert result["success"] is True
    assert result["action"] == "trial_activated"


@pytest.mark.asyncio
async def test_execute_trial_not_allowed(mem):
    mem.config = {"allow_free_trial": False}
    result = await mem.execute_tool("membership_trial", {"plan_key": "premium"}, "+56910000001", "tc6", {})
    assert result["success"] is False
    assert "not allowed" in result["error"]


@pytest.mark.asyncio
async def test_execute_check(mem):
    result = await mem.execute_tool("membership_check", {}, "+56910000001", "tc7", {})
    assert result["success"] is True
    assert result["action"] == "membership_checked"


@pytest.mark.asyncio
async def test_execute_get_plans(mem):
    result = await mem.execute_tool("membership_get_plans", {}, "+56910000001", "tc8", {})
    assert result["success"] is True
    assert result["action"] == "get_plans"
    assert len(result["plans"]) == 3


@pytest.mark.asyncio
async def test_execute_unknown_tool(mem):
    result = await mem.execute_tool("unknown_tool", {}, "+56910000001", "tc9", {})
    assert result["success"] is False
    assert "Unknown tool" in result["error"]


def test_parallel_safe_and_sequential_tools():
    inst = MembershipCapability()
    assert {"membership_check", "membership_get_plans"} == inst.PARALLEL_SAFE_TOOLS
    assert {"membership_activate", "membership_cancel", "membership_trial"} == inst.SEQUENTIAL_TOOLS
