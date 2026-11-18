"""Runtime context for a single Omi Vanguard task execution."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Event, RLock
from typing import Any, Dict, Optional


class ExecutionContextError(RuntimeError):
    """Base exception for execution-context errors."""


class ExecutionCancelledError(ExecutionContextError):
    """Raised when execution has been cancelled."""


class ExecutionTimeoutError(ExecutionContextError):
    """Raised when execution exceeds its configured timeout."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ExecutionContext:
    """Stores runtime information and controls for one task execution."""

    task_id: str
    platform: Optional[str] = None
    principal: str = "system"
    confirmed: bool = False
    timeout_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    _cancel_event: Event = field(
        default_factory=Event, init=False, repr=False
    )
    _lock: RLock = field(
        default_factory=RLock, init=False, repr=False
    )
    _started_at: datetime = field(
        default_factory=_utc_now, init=False
    )
    _completed_at: Optional[datetime] = field(
        default=None, init=False
    )
    _step_states: Dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _step_results: Dict[str, Any] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be a non-empty string")

        if not isinstance(self.principal, str) or not self.principal.strip():
            raise ValueError("principal must be a non-empty string")

        if self.platform is not None:
            if not isinstance(self.platform, str) or not self.platform.strip():
                raise ValueError("platform must be a non-empty string or None")

        if not isinstance(self.confirmed, bool):
            raise TypeError("confirmed must be a bool")

        if self.timeout_seconds is not None:
            if (
                isinstance(self.timeout_seconds, bool)
                or not isinstance(self.timeout_seconds, (int, float))
            ):
                raise TypeError("timeout_seconds must be a positive number or None")

            if self.timeout_seconds <= 0:
                raise ValueError("timeout_seconds must be greater than zero")

        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary")

        self.metadata = deepcopy(self.metadata)

    @property
    def started_at(self) -> datetime:
        return self._started_at

    @property
    def completed_at(self) -> Optional[datetime]:
        with self._lock:
            return self._completed_at

    @property
    def deadline(self) -> Optional[datetime]:
        if self.timeout_seconds is None:
            return None

        return self._started_at + timedelta(
            seconds=float(self.timeout_seconds)
        )

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def is_completed(self) -> bool:
        with self._lock:
            return self._completed_at is not None

    def request_cancel(self) -> None:
        """Request cancellation of this task."""
        self._cancel_event.set()

    def check_active(self) -> None:
        """Raise an exception if execution should stop."""
        if self._cancel_event.is_set():
            raise ExecutionCancelledError(
                f"Task '{self.task_id}' was cancelled"
            )

        deadline = self.deadline

        if deadline is not None and _utc_now() >= deadline:
            raise ExecutionTimeoutError(
                f"Task '{self.task_id}' exceeded its timeout"
            )

    def set_metadata(self, key: str, value: Any) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("metadata key must be a non-empty string")

        with self._lock:
            self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.metadata.get(key, default)

    def mark_step(
        self,
        step_id: str,
        status: str,
        result: Any = None,
    ) -> None:
        """Record a step's current status and optional result."""
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("step_id must be a non-empty string")

        if not isinstance(status, str) or not status.strip():
            raise ValueError("status must be a non-empty string")

        with self._lock:
            self._step_states[step_id] = status

            if result is not None:
                self._step_results[step_id] = result

    def get_step_status(self, step_id: str) -> Optional[str]:
        with self._lock:
            return self._step_states.get(step_id)

    def get_step_result(self, step_id: str) -> Any:
        with self._lock:
            return self._step_results.get(step_id)

    def finish(self) -> datetime:
        """Mark execution as completed. Repeated calls are safe."""
        with self._lock:
            if self._completed_at is None:
                self._completed_at = _utc_now()

            return self._completed_at

    def snapshot(self) -> Dict[str, Any]:
        """Return a snapshot of the execution state."""
        with self._lock:
            return {
                "task_id": self.task_id,
                "platform": self.platform,
                "principal": self.principal,
                "confirmed": self.confirmed,
                "started_at": self._started_at.isoformat(),
                "completed_at": (
                    self._completed_at.isoformat()
                    if self._completed_at
                    else None
                ),
                "cancelled": self._cancel_event.is_set(),
                "metadata": deepcopy(self.metadata),
                "step_states": deepcopy(self._step_states),
            }
