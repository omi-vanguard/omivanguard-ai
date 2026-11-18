"""Thread-safe event dispatch for Omi Vanguard task execution."""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable, Deque, Dict, List, Optional
from uuid import uuid4


class EventSystemError(RuntimeError):
    """Base exception for event-system errors."""


class EventValidationError(EventSystemError, ValueError):
    """Raised when an event or subscription is invalid."""


@dataclass(frozen=True)
class Event:
    """An immutable event envelope."""

    event_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise EventValidationError("event_type must be a non-empty string")
        if not isinstance(self.payload, dict):
            raise EventValidationError("payload must be a dictionary")
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise EventValidationError("event_id must be a non-empty string")
        if not isinstance(self.occurred_at, datetime):
            raise EventValidationError("occurred_at must be a datetime")
        if self.occurred_at.tzinfo is None:
            raise EventValidationError("occurred_at must be timezone-aware")
        object.__setattr__(self, "payload", deepcopy(self.payload))


@dataclass(frozen=True)
class ListenerFailure:
    subscription_id: str
    error: str


@dataclass(frozen=True)
class DispatchResult:
    event_id: str
    delivered: int
    failures: tuple


@dataclass(frozen=True)
class _Subscription:
    subscription_id: str
    event_type: str
    callback: Callable[[Event], Any]


class EventSystem:
    """Synchronous, thread-safe event dispatcher with bounded history."""

    def __init__(self, max_history: int = 1000) -> None:
        if isinstance(max_history, bool) or not isinstance(max_history, int):
            raise TypeError("max_history must be a non-negative integer")
        if max_history < 0:
            raise ValueError("max_history cannot be negative")

        self._lock = RLock()
        self._subscriptions: Dict[str, _Subscription] = {}
        self._history: Deque[Event] = deque(maxlen=max_history)

    def subscribe(
        self, event_type: str, callback: Callable[[Event], Any]
    ) -> str:
        """Register a callback and return its subscription ID."""
        if not isinstance(event_type, str) or not event_type.strip():
            raise EventValidationError("event_type must be a non-empty string")
        if not callable(callback):
            raise EventValidationError("callback must be callable")

        subscription_id = str(uuid4())
        subscription = _Subscription(subscription_id, event_type, callback)

        with self._lock:
            self._subscriptions[subscription_id] = subscription

        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription; return False if it does not exist."""
        if not isinstance(subscription_id, str) or not subscription_id.strip():
            raise EventValidationError(
                "subscription_id must be a non-empty string"
            )

        with self._lock:
            return self._subscriptions.pop(subscription_id, None) is not None

    def emit(
        self, event_type: str, payload: Optional[Dict[str, Any]] = None
    ) -> DispatchResult:
        """Dispatch an event without letting one listener stop the others."""
        event = Event(
            event_type=event_type,
            payload={} if payload is None else payload,
        )

        with self._lock:
            if self._history.maxlen != 0:
                self._history.append(event)
            listeners = tuple(
                subscription
                for subscription in self._subscriptions.values()
                if subscription.event_type == event.event_type
            )

        failures: List[ListenerFailure] = []
        delivered = 0

        for subscription in listeners:
            try:
                listener_event = Event(
                    event_type=event.event_type,
                    payload=deepcopy(event.payload),
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                )
                subscription.callback(listener_event)
                delivered += 1
            except Exception as exc:
                failures.append(
                    ListenerFailure(
                        subscription_id=subscription.subscription_id,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

        return DispatchResult(
            event_id=event.event_id,
            delivered=delivered,
            failures=tuple(failures),
        )

    def get_history(
        self, event_type: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Event]:
        """Return independent copies of recent events."""
        if event_type is not None and (
            not isinstance(event_type, str) or not event_type.strip()
        ):
            raise EventValidationError(
                "event_type must be a non-empty string or None"
            )

        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise TypeError("limit must be a non-negative integer or None")
            if limit < 0:
                raise ValueError("limit cannot be negative")

        with self._lock:
            events = list(self._history)

        if event_type is not None:
            events = [event for event in events if event.event_type == event_type]

        if limit is not None:
            events = events[-limit:] if limit else []

        return [
            Event(
                event_type=event.event_type,
                payload=deepcopy(event.payload),
                event_id=event.event_id,
                occurred_at=event.occurred_at,
            )
            for event in events
        ]

    def clear_history(self) -> None:
        """Clear stored event history without changing subscriptions."""
        with self._lock:
            self._history.clear()

    def get_status(self) -> Dict[str, Any]:
        """Return basic dispatcher statistics."""
        with self._lock:
            counts: Dict[str, int] = {}
            for subscription in self._subscriptions.values():
                counts[subscription.event_type] = (
                    counts.get(subscription.event_type, 0) + 1
                )

            return {
                "subscription_count": len(self._subscriptions),
                "history_count": len(self._history),
                "event_type_subscriptions": counts,
            }
