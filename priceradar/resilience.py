from __future__ import annotations

import threading
from typing import Optional

import structlog
from pybreaker import CircuitBreaker, CircuitBreakerListener

logger = structlog.get_logger(__name__)


class SourceCircuitBreakerListener(CircuitBreakerListener):
    def state_change(
        self,
        cb: CircuitBreaker,
        old_state: object,
        new_state: object,
    ) -> None:
        logger.info(
            "circuit_breaker_state_change",
            source=cb.name,
            before=str(old_state),
            after=str(new_state),
        )

    def failure(
        self,
        cb: CircuitBreaker,
        exc: BaseException,
    ) -> None:
        logger.warning(
            "circuit_breaker_failure",
            source=cb.name,
            exception=type(exc).__name__,
            message=str(exc),
        )

    def success(self, cb: CircuitBreaker) -> None:
        logger.debug(
            "circuit_breaker_success",
            source=cb.name,
        )


class SourceCircuitBreakerManager:
    def __init__(self) -> None:
        self._instances: dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()
        self._listener = SourceCircuitBreakerListener()

    def get_breaker(self, source_name: str) -> CircuitBreaker:
        if source_name in self._instances:
            return self._instances[source_name]

        with self._lock:
            if source_name in self._instances:
                return self._instances[source_name]

            breaker = CircuitBreaker(
                fail_max=5,
                reset_timeout=60,
                success_threshold=2,
                listeners=[self._listener],
                name=source_name,
                exclude=[ValueError, KeyError, AttributeError],
            )
            self._instances[source_name] = breaker
            return breaker


_manager: Optional[SourceCircuitBreakerManager] = None
_manager_lock = threading.Lock()


def get_circuit_breaker_manager() -> SourceCircuitBreakerManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SourceCircuitBreakerManager()
    return _manager
