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
    PARALLEL_SAFE_TOOLS: ClassVar[set[str]] = {"membership_check", "membership_get_plans"}
    SEQUENTIAL_TOOLS: ClassVar[set[str]] = {"membership_activate", "membership_cancel", "membership_trial"}

    _TOOL_DEFINITIONS: ClassVar[list[dict[str, Any]]] = [
        {
            "type": "function",
            "function": {
                "name": "membership_activate",
                "description": (
                    "Llama esta funcion UNICAMENTE cuando el cliente haya confirmado "
                    "explicitamente que quiere activar un plan de membresia. "
                    "NO la llames si el cliente solo pregunta por planes o precios. "
                    "Ejemplos de cuando llamarla: 'quiero el plan premium', 'activame el anual'. "
                    "Ejemplos de cuando NO llamarla: 'que planes tienen?', 'cuanto cuesta el premium?'"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "plan_key": {"type": "string", "description": "Clave del plan (ej: basico, premium, anual)"},
                    },
                    "required": ["plan_key"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "membership_cancel",
                "description": (
                    "Llama esta funcion cuando el cliente quiera cancelar su membresia activa. "
                    "Es una accion destructiva — asegurate de que el cliente confirmo la cancelacion."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "membership_trial",
                "description": (
                    "Llama esta funcion cuando el cliente quiera activar un trial gratuito. "
                    "Solo disponible si la config lo permite. "
                    "El cliente debe confirmar explicitamente que quiere el trial."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "plan_key": {"type": "string", "description": "Clave del plan para el trial"},
                    },
                    "required": ["plan_key"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "membership_check",
                "description": "Consultar el estado de la membresia del cliente. Retorna estado actual o indica que no tiene membresia.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "membership_get_plans",
                "description": "Listar los planes de membresia disponibles con precios y caracteristicas.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

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

    def _membership_state_dict(self, phone: str) -> dict[str, Any]:
        m = self._memberships.get(phone)
        if not m or m["status"] not in ("active", "trial"):
            return {"status": "none", "plan": None, "started_at": None, "next_billing": None}
        return {
            "status": m["status"],
            "plan_key": m["plan_key"],
            "plan_name": self._plan_name(m["plan_key"]),
            "price": self._plan_price(m["plan_key"]),
            "started_at": m["started_at"],
            "next_billing": m["next_billing"],
        }

    def get_tool_definitions(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        return list(self._TOOL_DEFINITIONS)

    def get_tool_names(self) -> set[str]:
        return {"membership_activate", "membership_cancel", "membership_trial", "membership_check", "membership_get_plans"}

    async def execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        phone: str,
        tool_call_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        if name == "membership_activate":
            return await self._execute_activate(args, phone)
        if name == "membership_cancel":
            return await self._execute_cancel(phone)
        if name == "membership_trial":
            return await self._execute_trial(args, phone)
        if name == "membership_check":
            return await self._execute_check(phone)
        if name == "membership_get_plans":
            return self._execute_get_plans()
        return {"success": False, "error": f"Unknown tool: {name}"}

    async def _execute_activate(self, args: dict[str, Any], phone: str) -> dict[str, Any]:
        plan_key = args.get("plan_key", "")
        valid_keys = [p["key"] for p in self._plans]
        if plan_key not in valid_keys:
            return {
                "success": False,
                "error": f"plan_key '{plan_key}' not found",
                "valid_plan_keys": valid_keys,
                "instruction": "Usa una de las claves de plan validas.",
            }
        await self.activate_plan(phone, plan_key)
        return {
            "success": True,
            "action": "membership_activated",
            "membership_state": self._membership_state_dict(phone),
        }

    async def _execute_cancel(self, phone: str) -> dict[str, Any]:
        await self._ensure_loaded(phone)
        m = self._memberships.get(phone)
        if not m or m["status"] not in ("active", "trial"):
            return {"success": False, "error": "No active membership to cancel", "membership_state": self._membership_state_dict(phone)}
        await self.cancel_membership(phone)
        return {
            "success": True,
            "action": "membership_cancelled",
            "membership_state": self._membership_state_dict(phone),
        }

    async def _execute_trial(self, args: dict[str, Any], phone: str) -> dict[str, Any]:
        if not self._allow_free_trial():
            return {
                "success": False,
                "error": "Free trial is not allowed for this agent",
                "instruction": "Informa al cliente que no hay trial disponible.",
            }
        plan_key = args.get("plan_key", "")
        valid_keys = [p["key"] for p in self._plans]
        if plan_key not in valid_keys:
            return {
                "success": False,
                "error": f"plan_key '{plan_key}' not found",
                "valid_plan_keys": valid_keys,
                "instruction": "Usa una de las claves de plan validas.",
            }
        await self._ensure_loaded(phone)
        existing = self._memberships.get(phone)
        if existing and existing["status"] in ("active", "trial"):
            return {
                "success": False,
                "error": f"Client already has an {existing['status']} membership",
                "membership_state": self._membership_state_dict(phone),
            }
        await self.activate_trial(phone, plan_key)
        return {
            "success": True,
            "action": "trial_activated",
            "trial_days": self._trial_days(),
            "membership_state": self._membership_state_dict(phone),
        }

    async def _execute_check(self, phone: str) -> dict[str, Any]:
        await self._ensure_loaded(phone)
        return {
            "success": True,
            "action": "membership_checked",
            "membership_state": self._membership_state_dict(phone),
        }

    def _execute_get_plans(self) -> dict[str, Any]:
        plans = [
            {
                "key": p["key"],
                "name": p["name"],
                "price": p["price"],
                "billing_cycle": p["billing_cycle"],
                "features": p.get("features", []),
            }
            for p in self._plans
        ]
        return {"success": True, "action": "get_plans", "plans": plans, "free_trial_available": self._allow_free_trial(), "trial_days": self._trial_days() if self._allow_free_trial() else 0}

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
