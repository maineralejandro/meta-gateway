from unittest.mock import AsyncMock, patch

import pytest

from core.capabilities.lead import (
    LEAD_STAGE_RE,
    LEAD_UPDATE_RE,
    LeadCapability,
)


@pytest.fixture
def lead_inst():
    inst = LeadCapability()
    inst._ensure_loaded = AsyncMock()
    inst._persist = AsyncMock()
    return inst


def test_lead_update_re_matches():
    m = LEAD_UPDATE_RE.search("text [LEAD_UPDATE:presupuesto:150M-200M] more")
    assert m is not None
    assert m.group(1) == "presupuesto"
    assert m.group(2) == "150M-200M"


def test_lead_stage_re_matches():
    m = LEAD_STAGE_RE.search("text [LEAD_STAGE:calificado] more")
    assert m is not None
    assert m.group(1) == "calificado"


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
async def test_parse_tags_update(lead_inst):
    text = "Presupuesto anotado [LEAD_UPDATE:presupuesto:150M-200M]"
    cleaned = await lead_inst.parse_tags("+56910000001", text, {})
    assert "[LEAD_UPDATE" not in cleaned
    result = await lead_inst.get_lead("+56910000001")
    assert result["data"]["presupuesto"] == "150M-200M"


@pytest.mark.asyncio
async def test_parse_tags_stage(lead_inst):
    text = "Lead calificado [LEAD_STAGE:calificado]"
    cleaned = await lead_inst.parse_tags("+56910000001", text, {})
    assert "[LEAD_STAGE" not in cleaned
    result = await lead_inst.get_lead("+56910000001")
    assert result["stage"] == "calificado"


@pytest.mark.asyncio
async def test_parse_tags_multiple_updates(lead_inst):
    text = "Datos [LEAD_UPDATE:presupuesto:150M-200M][LEAD_UPDATE:zona:providencia]"
    await lead_inst.parse_tags("+56910000001", text, {})
    result = await lead_inst.get_lead("+56910000001")
    assert result["data"]["presupuesto"] == "150M-200M"
    assert result["data"]["zona"] == "providencia"


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


def test_get_prompt_instructions():
    inst = LeadCapability(config={
        "stages": ["interesado", "calificado", "cerrado"],
        "fields": ["presupuesto", "zona"],
    })
    instructions = inst.get_prompt_instructions({})
    assert "LEAD_UPDATE" in instructions
    assert "LEAD_STAGE" in instructions
    assert "presupuesto" in instructions
    assert "interesado" in instructions


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
