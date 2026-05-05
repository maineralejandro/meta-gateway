import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import structlog

from core.capabilities.base import BaseCapability

logger = structlog.get_logger()

MEMBERSHIP_CHECK_RE = re.compile(r"\[MEMBERSHIP_CHECK\]")
MEMBERSHIP_PLAN_RE = re.compile(r"\[MEMBERSHIP_PLAN:([a-z_0-9]+)\]")
MEMBERSHIP_CANCEL_RE = re.compile(r"\[MEMBERSHIP_CANCEL\]")
MEMBERSHIP_TRIAL_RE = re.compile(r"\[MEMBERSHIP_TRIAL:([a-z_0-9]+)\]")

DEFAULT_PLANS: list[dict[str, Any]] = [
    {"key": "basico", "name": "Basico Mensual", "price": 15000, "billing_cycle": "monthly", "features": ["acceso gym", "lockers"]},
    {"key": "premium", "name": "Premium Mensual", "price": 30000, "billing_cycle": "monthly", "features": ["acceso gym", "clases", "lockers", "vestuario"]},
    {"key": "anual", "name": "Anual", "price": 250000, "billing_cycle": "yearly", "features": ["acceso gym", "clases", "lockers", "vestuario", "invitados"]},
]


class MembershipCapability(BaseCapability):
    name = "membership"
    description = "Membership plan management with billing cycles and free trial support"
    config_schema: ClassVar[list[dict[str, Any]]] = [
        {"key": "allow_free_trial", "type": "boolean", "label": "Allow Free Trial", "default": False},
        {"key": "trial_days", "type": "integer", "label": "Trial Duration (days)", "default": 7},
    ]
    tag_patterns: ClassVar[dict[str, re.Pattern[str]]] = {
        "MEMBERSHIP_CHECK": MEMBERSHIP_CHECK_RE,
        "MEMBERSHIP_PLAN": MEMBERSHIP_PLAN_RE,
        "MEMBERSHIP_CANCEL": MEMBERSHIP_CANCEL_RE,
        "MEMBERSHIP_TRIAL": MEMBERSHIP_TRIAL_RE,
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._memberships: dict[str, dict[str, Any]] = {}
        self._plans: list[dict[str, Any]] = DEFAULT_PLANS
        self._loaded_phones: set[str] = set()

    async def _ensure_loaded(self, phone: str) -> None:
        if phone in self._loaded_phones:
            return
        try:
            from db.database import get_db
            db = await get_db()
            row = await db.load_membership(phone)
            if row:
                self._memberships[phone] = {
                    "plan_key": row["plan_key"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "next_billing": row["next_billing"],
                }
            plans_rows = await db.load_plans()
            if plans_rows:
                self._plans = [
                    {
                        "key": r["key"],
                        "name": r["name"],
                        "price": r["price"],
                        "billing_cycle": r["billing_cycle"],
                        "features": json.loads(r["features"]) if isinstance(r["features"], str) else r["features"],
                    }
                    for r in plans_rows
                ]
        except Exception as e:
            logger.error("membership_load_error", phone=phone, error=str(e))
        self._loaded_phones.add(phone)

    async def _persist_membership(self, phone: str, plan_key: str, status: str, started_at: str, next_billing: str) -> None:
        try:
            from db.database import get_db
            db = await get_db()
            await db.save_membership(phone, plan_key, status, started_at, next_billing)
        except Exception as e:
            logger.error("membership_persist_error", phone=phone, error=str(e))

    async def _cancel_membership_db(self, phone: str) -> None:
        try:
            from db.database import get_db
            db = await get_db()
            await db.cancel_membership(phone)
        except Exception as e:
            logger.error("membership_cancel_error", phone=phone, error=str(e))

    def _plan_name(self, plan_key: str) -> str:
        for p in self._plans:
            if p["key"] == plan_key:
                return str(p["name"])
        return plan_key

    def _plan_price(self, plan_key: str) -> int:
        for p in self._plans:
            if p["key"] == plan_key:
                return int(p["price"])
        return 0

    def _next_billing_date(self, plan_key: str, start_date: str) -> str:
        for p in self._plans:
            if p["key"] == plan_key:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                if p["billing_cycle"] == "yearly":
                    next_date = start + timedelta(days=365)
                else:
                    next_date = start + timedelta(days=30)
                return next_date.strftime("%Y-%m-%d")
        start = datetime.strptime(start_date, "%Y-%m-%d")
        return (start + timedelta(days=30)).strftime("%Y-%m-%d")

    def _allow_free_trial(self) -> bool:
        val = self.config.get("allow_free_trial", False)
        return bool(val)

    def _trial_days(self) -> int:
        val = self.config.get("trial_days", 7)
        return int(val) if isinstance(val, (int, float)) else 7

    async def activate_plan(self, phone: str, plan_key: str) -> None:
        await self._ensure_loaded(phone)
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        next_billing = self._next_billing_date(plan_key, today)
        self._memberships[phone] = {
            "plan_key": plan_key,
            "status": "active",
            "started_at": today,
            "next_billing": next_billing,
        }
        await self._persist_membership(phone, plan_key, "active", today, next_billing)
        logger.info("membership_activated", phone=phone, plan=plan_key)

    async def cancel_membership(self, phone: str) -> None:
        await self._ensure_loaded(phone)
        membership = self._memberships.get(phone)
        if membership and membership["status"] in ("active", "trial"):
            membership["status"] = "cancelled"
            await self._cancel_membership_db(phone)
            logger.info("membership_cancelled", phone=phone)

    async def activate_trial(self, phone: str, plan_key: str) -> None:
        if not self._allow_free_trial():
            logger.warning("trial_not_allowed", phone=phone)
            return
        await self._ensure_loaded(phone)
        existing = self._memberships.get(phone)
        if existing and existing["status"] in ("active", "trial"):
            logger.warning("trial_already_active", phone=phone, status=existing["status"])
            return
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        trial_end = (datetime.now(UTC) + timedelta(days=self._trial_days())).strftime("%Y-%m-%d")
        self._memberships[phone] = {
            "plan_key": plan_key,
            "status": "trial",
            "started_at": today,
            "next_billing": trial_end,
        }
        await self._persist_membership(phone, plan_key, "trial", today, trial_end)
        logger.info("membership_trial_activated", phone=phone, plan=plan_key, trial_days=self._trial_days())

    async def get_membership(self, phone: str) -> dict[str, Any] | None:
        await self._ensure_loaded(phone)
        return self._memberships.get(phone)

    def get_plans(self) -> list[dict[str, Any]]:
        return list(self._plans)

    async def format_for_context(self, phone: str, config: dict[str, Any]) -> str | None:
        await self._ensure_loaded(phone)
        m = self._memberships.get(phone)
        if not m or m["status"] not in ("active", "trial"):
            return None
        plan_name = self._plan_name(m["plan_key"])
        price = self._plan_price(m["plan_key"])
        status_label = "Prueba gratis" if m["status"] == "trial" else "Activa"
        lines = [
            "Membresia del cliente:",
            f"- Plan: {plan_name}",
        ]
        if m["status"] == "trial":
            lines.append(f"- Estado: {status_label} (termina {m['next_billing']})")
            lines.append(f"- Precio despues del trial: ${price:,}")
        else:
            lines.append(f"- Precio: ${price:,}")
            lines.append(f"- Proximo cobro: {m['next_billing']}")
            lines.append(f"- Estado: {status_label}")
        lines.append(f"- Inicio: {m['started_at']}")
        return "\n".join(lines)

    async def parse_tags(self, phone: str, text: str, config: dict[str, Any]) -> str:
        for match in MEMBERSHIP_PLAN_RE.finditer(text):
            plan_key = match.group(1)
            await self.activate_plan(phone, plan_key)

        for match in MEMBERSHIP_TRIAL_RE.finditer(text):
            plan_key = match.group(1)
            await self.activate_trial(phone, plan_key)

        if MEMBERSHIP_CANCEL_RE.search(text):
            await self.cancel_membership(phone)

        cleaned = MEMBERSHIP_CHECK_RE.sub("", text)
        cleaned = MEMBERSHIP_PLAN_RE.sub("", cleaned)
        cleaned = MEMBERSHIP_CANCEL_RE.sub("", cleaned)
        cleaned = MEMBERSHIP_TRIAL_RE.sub("", cleaned)
        return cleaned.strip()

    async def clear(self, phone: str, config: dict[str, Any]) -> None:
        self._memberships.pop(phone, None)
        self._loaded_phones.discard(phone)

    def get_prompt_instructions(self, config: dict[str, Any]) -> str:
        plans_str = ", ".join(f"{p['key']} (${p['price']:,})" for p in self._plans)
        allow_trial = self._allow_free_trial()
        instructions = (
            "GESTION DE MEMBRESIAS (OBLIGATORIO):\n"
            "Cuando el cliente elija un plan, incluye al final de tu respuesta: "
            "[MEMBERSHIP_PLAN:clave_plan]\n"
            f"Planes disponibles: {plans_str}\n\n"
            "Cuando el cliente cancele: [MEMBERSHIP_CANCEL]\n"
            "Para consultar estado: [MEMBERSHIP_CHECK]\n"
        )
        if allow_trial:
            instructions += (
                f"Si el cliente quiere probar antes: [MEMBERSHIP_TRIAL:clave_plan] "
                f"(trial de {self._trial_days()} dias)\n"
            )
        instructions += "\nLos tags NO son visibles para el cliente."
        return instructions
