from unittest.mock import AsyncMock, patch

import pytest

from core.capabilities.appointment import (
    APPOINTMENT_ADD_RE,
    APPOINTMENT_AVAILABLE_RE,
    APPOINTMENT_CANCEL_RE,
    AppointmentCapability,
)


@pytest.fixture
def appt():
    inst = AppointmentCapability()
    inst._ensure_loaded = AsyncMock()
    inst._persist_appointment = AsyncMock()
    inst._cancel_appointment = AsyncMock()
    return inst


def test_appointment_add_re_matches():
    m = APPOINTMENT_ADD_RE.search("text [APPOINTMENT_ADD:2025-05-05:14:00:limpieza] more")
    assert m is not None
    assert m.group(1) == "2025-05-05"
    assert m.group(2) == "14:00"
    assert m.group(3) == "limpieza"


def test_appointment_cancel_re_matches():
    m = APPOINTMENT_CANCEL_RE.search("text [APPOINTMENT_CANCEL:2025-05-05:14:00] more")
    assert m is not None
    assert m.group(1) == "2025-05-05"
    assert m.group(2) == "14:00"


def test_appointment_available_re_matches():
    m = APPOINTMENT_AVAILABLE_RE.search("[APPOINTMENT_AVAILABLE:2025-05-05]")
    assert m is not None
    assert m.group(1) == "2025-05-05"


@pytest.mark.asyncio
async def test_add_appointment(appt):
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "limpieza")
    appts = await appt.get_appointments("+56910000001")
    assert len(appts) == 1
    assert appts[0]["date"] == "2025-05-05"
    assert appts[0]["time"] == "14:00"
    assert appts[0]["service_key"] == "limpieza"
    assert appts[0]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_add_appointment_duplicate_slot(appt):
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "limpieza")
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "control")
    appts = await appt.get_appointments("+56910000001")
    assert len(appts) == 1


@pytest.mark.asyncio
async def test_cancel_appointment(appt):
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "limpieza")
    await appt.cancel_appointment("+56910000001", "2025-05-05", "14:00")
    appts = await appt.get_appointments("+56910000001")
    assert len(appts) == 0


@pytest.mark.asyncio
async def test_parse_tags_add(appt):
    text = "Tu cita queda agendada [APPOINTMENT_ADD:2025-05-05:14:00:limpieza]"
    cleaned = await appt.parse_tags("+56910000001", text, {})
    assert "[APPOINTMENT_ADD" not in cleaned
    appts = await appt.get_appointments("+56910000001")
    assert len(appts) == 1


@pytest.mark.asyncio
async def test_parse_tags_cancel(appt):
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "limpieza")
    text = "Cita cancelada [APPOINTMENT_CANCEL:2025-05-05:14:00]"
    cleaned = await appt.parse_tags("+56910000001", text, {})
    assert "[APPOINTMENT_CANCEL" not in cleaned
    appts = await appt.get_appointments("+56910000001")
    assert len(appts) == 0


@pytest.mark.asyncio
async def test_parse_tags_available_stripped(appt):
    text = "Revisando [APPOINTMENT_AVAILABLE:2025-05-05]"
    cleaned = await appt.parse_tags("+56910000001", text, {})
    assert "[APPOINTMENT_AVAILABLE" not in cleaned


@pytest.mark.asyncio
async def test_format_for_context_empty(appt):
    result = await appt.format_for_context("+56910000001", {})
    assert result is not None
    assert "Proximas horas disponibles" in result


@pytest.mark.asyncio
async def test_format_for_context_with_appointment(appt):
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "limpieza")
    result = await appt.format_for_context("+56910000001", {})
    assert result is not None
    assert "2025-05-05" in result
    assert "14:00" in result


@pytest.mark.asyncio
async def test_clear(appt):
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "limpieza")
    await appt.clear("+56910000001", {})
    appts = await appt.get_appointments("+56910000001")
    assert len(appts) == 0


def test_get_prompt_instructions():
    inst = AppointmentCapability(config={"services": [{"key": "limpieza", "name": "Limpieza dental"}]})
    instructions = inst.get_prompt_instructions({})
    assert "APPOINTMENT_ADD" in instructions
    assert "limpieza" in instructions


def test_get_available_slots_weekday():
    inst = AppointmentCapability(config={
        "business_hours": {"mon": "09:00-12:00", "tue": "09:00-18:00"},
        "slot_duration_minutes": 60,
    })
    slots = inst._get_available_slots_for_date("2025-05-06")
    assert "09:00" in slots
    assert "10:00" in slots
    assert "17:00" in slots


def test_get_available_slots_closed_sunday():
    inst = AppointmentCapability(config={
        "business_hours": {"sun": "closed"},
    })
    slots = inst._get_available_slots_for_date("2025-05-04")
    assert slots == []


@pytest.mark.asyncio
async def test_ensure_loaded_logs_error_on_db_failure():
    inst = AppointmentCapability()
    with patch("db.database.get_db", side_effect=RuntimeError("db down")):
        await inst._ensure_loaded("+56910000001")
    assert inst._appointments.get("+56910000001") == []


@pytest.mark.asyncio
async def test_multiple_phones_independent(appt):
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "limpieza")
    await appt.add_appointment("+56910000002", "2025-05-05", "15:00", "control")
    appts1 = await appt.get_appointments("+56910000001")
    appts2 = await appt.get_appointments("+56910000002")
    assert len(appts1) == 1
    assert len(appts2) == 1
    assert appts1[0]["service_key"] == "limpieza"
    assert appts2[0]["service_key"] == "control"


def test_get_tool_definitions():
    inst = AppointmentCapability()
    defs = inst.get_tool_definitions({})
    assert len(defs) == 3
    names = [d["function"]["name"] for d in defs]
    assert "appointment_add" in names
    assert "appointment_cancel" in names
    assert "appointment_get_available" in names


def test_get_tool_names():
    inst = AppointmentCapability()
    names = inst.get_tool_names()
    assert names == {"appointment_add", "appointment_cancel", "appointment_get_available"}


@pytest.mark.asyncio
async def test_execute_add(appt):
    result = await appt.execute_tool("appointment_add", {"date": "2025-05-05", "time": "14:00", "service_key": "limpieza"}, "+56910000001", "tc1", {})
    assert result["success"] is True
    assert result["action"] == "appointment_added"


@pytest.mark.asyncio
async def test_execute_add_duplicate_slot(appt):
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "limpieza")
    result = await appt.execute_tool("appointment_add", {"date": "2025-05-05", "time": "14:00", "service_key": "control"}, "+56910000001", "tc2", {})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_execute_cancel(appt):
    await appt.add_appointment("+56910000001", "2025-05-05", "14:00", "limpieza")
    result = await appt.execute_tool("appointment_cancel", {"date": "2025-05-05", "time": "14:00"}, "+56910000001", "tc3", {})
    assert result["success"] is True
    assert result["action"] == "appointment_cancelled"


@pytest.mark.asyncio
async def test_execute_get_available(appt):
    result = await appt.execute_tool("appointment_get_available", {"date": "2025-05-05"}, "+56910000001", "tc4", {})
    assert result["success"] is True
    assert "available_slots" in result


@pytest.mark.asyncio
async def test_execute_unknown_tool(appt):
    result = await appt.execute_tool("unknown_tool", {}, "+56910000001", "tc5", {})
    assert result["success"] is False
    assert "Unknown tool" in result["error"]


def test_parallel_safe_and_sequential_tools():
    inst = AppointmentCapability()
    assert {"appointment_get_available"} == inst.PARALLEL_SAFE_TOOLS
    assert {"appointment_add", "appointment_cancel"} == inst.SEQUENTIAL_TOOLS
