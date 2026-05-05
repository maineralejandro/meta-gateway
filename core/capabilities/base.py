import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import structlog

logger = structlog.get_logger()


class BaseCapability(ABC):
    name: str = ""
    description: str = ""
    tag_patterns: ClassVar[dict[str, re.Pattern[str]]] = {}
    config_schema: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = config or {}

    @abstractmethod
    async def format_for_context(self, phone: str, config: dict[str, Any]) -> str | None:
        """Inject business state into LLM context. Return None if no state to inject."""

    @abstractmethod
    async def parse_tags(self, phone: str, text: str, config: dict[str, Any]) -> str:
        """Extract structured tags from LLM response, mutate state, return cleaned text."""

    @abstractmethod
    async def clear(self, phone: str, config: dict[str, Any]) -> None:
        """Reset state on session timeout."""

    @abstractmethod
    def get_prompt_instructions(self, config: dict[str, Any]) -> str:
        """Return system prompt instructions for this capability's tags."""


class CapabilityRegistry:
    _CACHE_TTL = 60.0

    def __init__(self) -> None:
        self._capabilities: dict[str, type[BaseCapability]] = {}
        self._cache: dict[int, tuple[float, list[BaseCapability]]] = {}

    def register(self, cls: type[BaseCapability]) -> None:
        if not cls.name:
            raise ValueError(f"Capability class {cls.__name__} must have a non-empty 'name' attribute")
        self._capabilities[cls.name] = cls

    def get_class(self, name: str) -> type[BaseCapability] | None:
        return self._capabilities.get(name)

    def list_available(self) -> list[str]:
        return sorted(self._capabilities.keys())

    def list_available_detailed(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for name in sorted(self._capabilities.keys()):
            cls = self._capabilities[name]
            result.append({
                "name": name,
                "description": cls.description,
                "config_schema": cls.config_schema,
            })
        return result

    def invalidate(self, agent_id: int | None = None) -> None:
        if agent_id is not None:
            self._cache.pop(agent_id, None)
        else:
            self._cache.clear()

    async def resolve(self, agent_id: int | None, *, force: bool = False) -> list[BaseCapability]:
        if agent_id is None:
            return []
        now = time.monotonic()
        if not force:
            entry = self._cache.get(agent_id)
            if entry and (now - entry[0]) < self._CACHE_TTL:
                return entry[1]
        from db.database import get_db
        db = await get_db()
        caps = await db.get_agent_capabilities(agent_id)
        instances: list[BaseCapability] = []
        for cap in caps:
            if cap.is_active:
                cls = self._capabilities.get(cap.capability_name)
                if cls:
                    try:
                        config = json.loads(cap.config_json) if cap.config_json else {}
                    except (json.JSONDecodeError, TypeError):
                        config = {}
                    instances.append(cls(config=config))
                else:
                    logger.warning(
                        "capability_not_registered",
                        capability_name=cap.capability_name,
                        agent_id=agent_id,
                    )
        self._cache[agent_id] = (now, instances)
        return instances


registry = CapabilityRegistry()
