class HermesError(Exception):
    """Base for all Hermes domain errors."""


class PersistError(HermesError):
    """DB write failed — caller must not update in-memory state."""


class InfraError(HermesError):
    """Infrastructure failure — DB connection, LLM timeout, Meta API unreachable."""


class ObservabilityError(HermesError):
    """Non-critical failure — trace save, sentiment analysis. Log + metric + continue."""
