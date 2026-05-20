from unittest.mock import AsyncMock, patch

import pytest

from core.capabilities.lead import LeadCapability


@pytest.fixture
def lead_inst():
    inst = LeadCapability()
    inst._ensure_loaded = AsyncMock()
    inst._persist = AsyncMock()
    return inst


@pytest.mark.asyncio
async def test_update_field(lead_inst):
    await lead_inst.update_field("+56910000001", "presupuesto", "150M-200M")
    result = await lead_inst.get_lead("+56910000001")
    assert result is not None
    assert result["data"]["presupuesto"] == "150M-200M"


@pytest.mark.asyncio
async def test_update_multiple_fields(lead_inst):
    await lead_inst.update_field("+56910000001", "presupuesto", "150M-200M")
    await lead_inst.update_field("+56910000001", "zona", "Providencia")
    result = await lead_inst.get_lead("+56910000001")
    assert result["data"]["presupuesto"] == "150M-200M"
    assert result["data"]["zona"] == "Providencia"


@pytest.mark.asyncio
async def test_advance_stage(lead_inst):
    await lead_inst.advance_stage("+56910000001", "calificado")
    result = await lead_inst.get_lead("+56910000001")
    assert result is not None
    assert result["stage"] == "calificado"


@pytest.mark.asyncio
async def test_advance_stage_invalid(lead_inst):
    await lead_inst.advance_stage("+56910000001", "nonexistent_stage")
    result = await lead_inst.get_lead("+56910000001")
    assert result is None


@pytest.mark.asyncio
async def test_format_for_context_no_lead(lead_inst):
    ctx = await lead_inst.format_for_context("+56910000001", {})
    assert ctx is None


@pytest.mark.asyncio
async def test_format_for_context_with_lead(lead_inst):
    await lead_inst.update_field("+56910000001", "presupuesto", "150M-200M")
    await lead_inst.advance_stage("+56910000001", "calificado")
    ctx = await lead_inst.format_for_context("+56910000001", {})
    assert ctx is not None
    assert "Calificado" in ctx
    assert "presupuesto" in ctx


@pytest.mark.asyncio
async def test_clear(lead_inst):
    await lead_inst.update_field("+56910000001", "presupuesto", "150M-200M")
    await lead_inst.clear("+56910000001", {})
    result = await lead_inst.get_lead("+56910000001")
    assert result is None


@pytest.mark.asyncio
async def test_ensure_loaded_logs_error_on_db_failure():
    inst = LeadCapability()
    with patch("db.database.get_db", side_effect=RuntimeError("db down")):
        await inst._ensure_loaded("+56910000001")
        assert inst._leads.get("+56910000001") is None


@pytest.mark.asyncio
async def test_default_stages_from_config():
    inst = LeadCapability(config={"stages": ["nuevo", "contactado", "ganado"], "fields": ["fuente"]})
    assert inst._get_stages() == ["nuevo", "contactado", "ganado"]
    assert inst._get_fields() == ["fuente"]


@pytest.mark.asyncio
async def test_default_stages_when_no_config():
    inst = LeadCapability()
    assert "interesado" in inst._get_stages()
    assert "presupuesto" in inst._get_fields()


def test_get_tool_definitions():
    inst = LeadCapability()
    defs = inst.get_tool_definitions({})
    assert len(defs) == 3
    names = [d["function"]["name"] for d in defs]
    assert "lead_update_field" in names
    assert "lead_advance_stage" in names
    assert "lead_get" in names


def test_get_tool_names():
    inst = LeadCapability()
    names = inst.get_tool_names()
    assert names == {"lead_update_field", "lead_advance_stage", "lead_get"}


@pytest.mark.asyncio
async def test_execute_update_field(lead_inst):
    result = await lead_inst.execute_tool("lead_update_field", {"field": "zona", "value": "Providencia"}, "+56910000001", "tc1", {})
    assert result["success"] is True
    assert result["action"] == "field_updated"
    assert result["lead_state"]["data"]["zona"] == "Providencia"


@pytest.mark.asyncio
async def test_execute_update_field_missing_field(lead_inst):
    result = await lead_inst.execute_tool("lead_update_field", {"value": "test"}, "+56910000001", "tc2", {})
    assert result["success"] is False
    assert "field is required" in result["error"]


@pytest.mark.asyncio
async def test_execute_advance_stage(lead_inst):
    result = await lead_inst.execute_tool("lead_advance_stage", {"stage": "calificado"}, "+56910000001", "tc3", {})
    assert result["success"] is True
    assert result["action"] == "stage_advanced"
    assert result["lead_state"]["stage"] == "calificado"


@pytest.mark.asyncio
async def test_execute_advance_stage_invalid(lead_inst):
    result = await lead_inst.execute_tool("lead_advance_stage", {"stage": "nonexistent"}, "+56910000001", "tc4", {})
    assert result["success"] is False
    assert "valid_stages" in result
    assert "instruction" in result


@pytest.mark.asyncio
async def test_execute_advance_stage_missing_stage(lead_inst):
    result = await lead_inst.execute_tool("lead_advance_stage", {}, "+56910000001", "tc5", {})
    assert result["success"] is False
    assert "stage is required" in result["error"]


@pytest.mark.asyncio
async def test_execute_get(lead_inst):
    await lead_inst.update_field("+56910000001", "zona", "Providencia")
    result = await lead_inst.execute_tool("lead_get", {}, "+56910000001", "tc6", {})
    assert result["success"] is True
    assert result["action"] == "lead_retrieved"
    assert result["lead_state"]["data"]["zona"] == "Providencia"


@pytest.mark.asyncio
async def test_execute_get_empty(lead_inst):
    result = await lead_inst.execute_tool("lead_get", {}, "+56910000001", "tc7", {})
    assert result["success"] is True
    assert result["lead_state"]["stage"] is None


@pytest.mark.asyncio
async def test_execute_unknown_tool(lead_inst):
    result = await lead_inst.execute_tool("unknown_tool", {}, "+56910000001", "tc8", {})
    assert result["success"] is False
    assert "Unknown tool" in result["error"]


def test_parallel_safe_and_sequential_tools():
    inst = LeadCapability()
    assert {"lead_get"} == inst.PARALLEL_SAFE_TOOLS
    assert {"lead_update_field", "lead_advance_stage"} == inst.SEQUENTIAL_TOOLS
