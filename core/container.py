from typing import Any

import structlog

logger = structlog.get_logger()


class ServiceContainer:
    def __init__(self) -> None:
        self._built = False

    def build(self) -> None:
        from core.hitl_router import HITLRouter
        from core.inference import InferenceEngine
        from core.memory import MemoryManager
        from core.meta_client import meta_client as default_meta_client
        from core.sentiment import SentimentAnalyzer
        from core.sessions import SessionManager
        from core.turn_builder import TurnBuilder
        from db.database import db, get_db

        self.meta_client = default_meta_client
        self.sentiment = SentimentAnalyzer()
        self.inference = InferenceEngine(db=db)
        self.memory = MemoryManager(db=db)
        self.sessions = SessionManager(db=db, memory_manager=self.memory)
        self.turn_builder = TurnBuilder(meta_client=self.meta_client)
        self.hitl_router = HITLRouter(
            db_getter=get_db,
            inference=self.inference,
            memory=self.memory,
            sentiment=self.sentiment,
            meta_client_override=self.meta_client,
        )
        self.turn_builder.set_process_turn_fn(self.hitl_router.process_turn)
        self._built = True

    def wire_singletons(self) -> None:
        if not self._built:
            raise RuntimeError("ServiceContainer.build() must be called before wire_singletons()")

        import core.hitl_router as _hr
        import core.inference as _inf
        import core.memory as _mem
        import core.sessions as _sess
        import core.turn_builder as _tb

        _inf.inference_engine = self.inference
        _mem.memory_manager = self.memory
        _sess.session_manager = self.sessions
        _tb.turn_builder = self.turn_builder
        _hr.hitl_router = self.hitl_router
        _hr.process_inbound_message = self.hitl_router.process_inbound_message

        logger.info("service_container_wired")


container = ServiceContainer()
