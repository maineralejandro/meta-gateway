import re
from datetime import datetime, timedelta
from typing import Any, ClassVar

import structlog

from core.capabilities.base import BaseCapability

logger = structlog.get_logger()

APPOINTMENT_ADD_RE = re.compile(r"\[APPOINTMENT_ADD:([0-9-]+):([0-9:]+):([a-z_0-9]+)\]")
APPOINTMENT_CANCEL_RE = re.compile(r"\[APPOINTMENT_CANCEL:([0-9-]+):([0-9:]+)\]")
APPOINTMENT_AVAILABLE_RE = re.compile(r"\[APPOINTMENT_AVAILABLE:([0-9-]+)\]")

DEFAULT_BUSINESS_HOURS: dict[str, str] = {
    "mon": "09:00-18:00",
    "tue": "09:00-18:00",
    "wed": "09:00-18:00",
    "thu": "09:00-18:00",
    "fri": "09:00-18:00",
    "sat": "10:00-14:00",
    "sun": "closed",
}

DAY_ABBR = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DAY_NAMES_ES: dict[str, str] = {
    "mon": "Lunes",
    "tue": "Martes",
    "wed": "Miércoles",
    "thu": "Jueves",
    "fri": "Viernes",
    "sat": "Sábado",
    "sun": "Domingo",
}


class AppointmentCapability(BaseCapability):
    name = "appointment"
    description = "Manages appointments with business hours and slot calculation"
    config_schema: ClassVar[list[dict[str, Any]]] = [
        {"key": "business_hours", "type": "object", "label": "Business Hours", "default": DEFAULT_BUSINESS_HOURS},
        {"key": "slot_duration_minutes", "type": "integer", "label": "Slot Duration (min)", "default": 30},
        {"key": "services", "type": "array", "label": "Services", "default": []},
        {"key": "timezone", "type": "string", "label": "Timezone", "default": "America/Santiago"},
        {"key": "max_advance_days", "type": "integer", "label": "Max Advance Days", "default": 30},
    ]
    tag_patterns: ClassVar[dict[str, re.Pattern[str]]] = {
        "APPOINTMENT_ADD": APPOINTMENT_ADD_RE,
        "APPOINTMENT_CANCEL": APPOINTMENT_CANCEL_RE,
        "APPOINTMENT_AVAILABLE": APPOINTMENT_AVAILABLE_RE,
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._appointments: dict[str, list[dict[str, Any]]] = {}
        self._loaded_phones: set[str] = set()

    def _get_business_hours(self) -> dict[str, str]:
        val = self.config.get("business_hours", DEFAULT_BUSINESS_HOURS)
        return val if isinstance(val, dict) else DEFAULT_BUSINESS_HOURS

    def _get_slot_duration(self) -> int:
        val = self.config.get("slot_duration_minutes", 30)
        return int(val) if isinstance(val, (int, float)) else 30

    def _get_services(self) -> list[dict[str, Any]]:
        val = self.config.get("services", [])
        return val if isinstance(val, list) else []

    def _get_timezone(self) -> str:
        val = self.config.get("timezone", "America/Santiago")
        return str(val)

    def _get_max_advance_days(self) -> int:
        val = self.config.get("max_advance_days", 30)
        return int(val) if isinstance(val, (int, float)) else 30

    async def _ensure_loaded(self, phone: str) -> None:
        if phone in self._loaded_phones:
            return
        try:
            from db.database import get_db
            db = await get_db()
            rows = await db.load_appointments(phone)
            self._appointments[phone] = [
                {
                    "date": row["date"],
                    "time": row["time"],
                    "service_key": row["service_key"],
                    "status": row["status"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error("appointment_load_error", phone=phone, error=str(e))
            self._appointments[phone] = []
        self._loaded_phones.add(phone)

    async def _persist_appointment(self, phone: str, date: str, time: str, service_key: str, status: str = "confirmed") -> None:
        try:
            from db.database import get_db
            db = await get_db()
            await db.save_appointment(phone, date, time, service_key, status)
        except Exception as e:
            logger.error("appointment_persist_error", phone=phone, error=str(e))

    async def _cancel_appointment(self, phone: str, date: str, time: str) -> None:
        try:
            from db.database import get_db
            db = await get_db()
            await db.cancel_appointment(phone, date, time)
        except Exception as e:
            logger.error("appointment_cancel_error", phone=phone, error=str(e))

    def _get_available_slots_for_date(self, date_str: str) -> list[str]:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return []
        day_abbr = DAY_ABBR[date.weekday()]
        hours_str = self._get_business_hours().get(day_abbr, "closed")
        if hours_str == "closed":
            return []
        try:
            open_str, close_str = hours_str.split("-")
            open_h, open_m = int(open_str.split(":")[0]), int(open_str.split(":")[1])
            close_h, close_m = int(close_str.split(":")[0]), int(close_str.split(":")[1])
        except (ValueError, IndexError):
            return []
        slot_duration = self._get_slot_duration()
        slots: list[str] = []
        current = datetime(date.year, date.month, date.day, open_h, open_m)
        close_time = datetime(date.year, date.month, date.day, close_h, close_m)
        while current + timedelta(minutes=slot_duration) <= close_time:
            slots.append(current.strftime("%H:%M"))
            current += timedelta(minutes=slot_duration)
        booked = {
            (a["date"], a["time"])
            for appts in self._appointments.values()
            for a in appts
            if a["date"] == date_str and a["status"] == "confirmed"
        }
        available = [s for s in slots if (date_str, s) not in booked]
        return available

    def _service_name(self, service_key: str) -> str:
        for svc in self._get_services():
            if svc.get("key") == service_key:
                name = svc.get("name", service_key)
                return str(name) if name is not None else service_key
        return service_key

    async def add_appointment(self, phone: str, date: str, time: str, service_key: str) -> None:
        await self._ensure_loaded(phone)
        existing = self._appointments.get(phone, [])
        for a in existing:
            if a["date"] == date and a["time"] == time and a["status"] == "confirmed":
                logger.warning("appointment_slot_taken", phone=phone, date=date, time=time)
                return
        new_appt = {"date": date, "time": time, "service_key": service_key, "status": "confirmed"}
        if phone not in self._appointments:
            self._appointments[phone] = []
        self._appointments[phone].append(new_appt)
        await self._persist_appointment(phone, date, time, service_key)
        logger.info("appointment_added", phone=phone, date=date, time=time, service=service_key)

    async def cancel_appointment(self, phone: str, date: str, time: str) -> None:
        await self._ensure_loaded(phone)
        appts = self._appointments.get(phone, [])
        for a in appts:
            if a["date"] == date and a["time"] == time and a["status"] == "confirmed":
                a["status"] = "cancelled"
                break
        await self._cancel_appointment(phone, date, time)
        logger.info("appointment_cancelled", phone=phone, date=date, time=time)

    async def get_appointments(self, phone: str) -> list[dict[str, Any]]:
        await self._ensure_loaded(phone)
        return [a for a in self._appointments.get(phone, []) if a["status"] == "confirmed"]

    async def format_for_context(self, phone: str, config: dict[str, Any]) -> str | None:
        await self._ensure_loaded(phone)
        appts = [a for a in self._appointments.get(phone, []) if a["status"] == "confirmed"]
        lines = []
        if appts:
            lines.append("Citas del cliente:")
            for a in sorted(appts, key=lambda x: (x["date"], x["time"])):
                svc_name = self._service_name(a["service_key"])
                date_obj = datetime.strptime(a["date"], "%Y-%m-%d")
                day_name = DAY_NAMES_ES.get(DAY_ABBR[date_obj.weekday()], "")
                lines.append(f"- {day_name} {a['date']} {a['time']} — {svc_name} (confirmada)")
        from datetime import date as date_mod
        today = date_mod.today()
        max_advance = self._get_max_advance_days()
        slots_lines = []
        for i in range(min(max_advance, 7)):
            d = today + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            slots = self._get_available_slots_for_date(d_str)
            if slots:
                day_name = DAY_NAMES_ES.get(DAY_ABBR[d.weekday()], "")
                slots_str = ", ".join(slots[:8])
                if len(slots) > 8:
                    slots_str += f" (+{len(slots) - 8} mas)"
                slots_lines.append(f"{day_name} {d_str}: {slots_str}")
        if slots_lines:
            lines.append("Proximas horas disponibles:")
            lines.extend(slots_lines)
        if not lines:
            return None
        return "\n".join(lines)

    async def parse_tags(self, phone: str, text: str, config: dict[str, Any]) -> str:
        for match in APPOINTMENT_ADD_RE.finditer(text):
            date, time, service_key = match.group(1), match.group(2), match.group(3)
            await self.add_appointment(phone, date, time, service_key)

        for match in APPOINTMENT_CANCEL_RE.finditer(text):
            date, time = match.group(1), match.group(2)
            await self.cancel_appointment(phone, date, time)

        cleaned = APPOINTMENT_ADD_RE.sub("", text)
        cleaned = APPOINTMENT_CANCEL_RE.sub("", cleaned)
        cleaned = APPOINTMENT_AVAILABLE_RE.sub("", cleaned)
        return cleaned.strip()

    async def clear(self, phone: str, config: dict[str, Any]) -> None:
        self._appointments.pop(phone, None)
        self._loaded_phones.discard(phone)

    def get_prompt_instructions(self, config: dict[str, Any]) -> str:
        services = self._get_services()
        services_str = ", ".join(s.get("key", "") for s in services) if services else "(configurar servicios)"
        return (
            "GESTIÓN DE CITAS (OBLIGATORIO):\n"
            "Cuando el cliente quiera agendar una cita, incluye al final de tu respuesta: "
            "[APPOINTMENT_ADD:fecha:hora:servicio]\n"
            "- fecha en formato YYYY-MM-DD\n"
            "- hora en formato HH:MM\n"
            f"- servicio: {services_str}\n\n"
            "Cuando el cliente cancele: [APPOINTMENT_CANCEL:fecha:hora]\n"
            "Para consultar disponibilidad: [APPOINTMENT_AVAILABLE:fecha]\n\n"
            "Los tags NO son visibles para el cliente."
        )
