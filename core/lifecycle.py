"""Lifecycle management for Omi Vanguard components."""

from threading import RLock
from typing import Any, Dict, List, Optional, Tuple


class LifecycleError(RuntimeError):
    """Raised when a lifecycle operation fails."""

    def __init__(
        self,
        message: str,
        failures: Optional[List[Tuple[str, Exception]]] = None,
    ) -> None:
        super().__init__(message)
        self.failures = tuple(failures or [])


class LifecycleManager:
    """Initialize components in registration order and close in reverse order."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._components: Dict[str, Any] = {}
        self._initialized: List[str] = []
        self._state = "stopped"

    def register(self, name: str, component: Any) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")

        if (
            component is None
            or not callable(getattr(component, "initialize", None))
            or not callable(getattr(component, "close", None))
        ):
            raise TypeError(
                "component must provide callable initialize() and close()"
            )

        with self._lock:
            if self._state != "stopped":
                raise LifecycleError(
                    "Components can only be registered while stopped"
                )

            if name in self._components:
                raise LifecycleError(
                    f"Component '{name}' is already registered"
                )

            self._components[name] = component

    def unregister(self, name: str) -> bool:
        with self._lock:
            if self._state != "stopped":
                raise LifecycleError(
                    "Components can only be unregistered while stopped"
                )

            return self._components.pop(name, None) is not None

    def initialize(self) -> None:
        with self._lock:
            if self._state == "running":
                return

            if self._state != "stopped":
                raise LifecycleError(
                    f"Cannot initialize while state is '{self._state}'"
                )

            self._state = "starting"
            components = list(self._components.items())

        initialized: List[str] = []
        rollback_failures: List[Tuple[str, Exception]] = []
        current_name: Optional[str] = None

        try:
            for current_name, component in components:
                try:
                    component.initialize()
                except Exception:
                    # Clean up a component that partially initialized.
                    try:
                        component.close()
                    except Exception as cleanup_exc:
                        rollback_failures.append(
                            (current_name, cleanup_exc)
                        )
                    raise

                initialized.append(current_name)

                with self._lock:
                    self._initialized = list(initialized)

            with self._lock:
                self._state = "running"

        except Exception as exc:
            for name in reversed(initialized):
                try:
                    self._components[name].close()
                except Exception as cleanup_exc:
                    rollback_failures.append(
                        (name, cleanup_exc)
                    )

            with self._lock:
                self._initialized = []
                self._state = "stopped"

            label = current_name if current_name is not None else "<none>"

            raise LifecycleError(
                f"Initialization failed for component '{label}': {exc}",
                rollback_failures,
            ) from exc

    def shutdown(self) -> None:
        with self._lock:
            if self._state == "stopped":
                return

            if self._state != "running":
                raise LifecycleError(
                    f"Cannot shut down while state is '{self._state}'"
                )

            self._state = "stopping"
            initialized = list(self._initialized)

        failures: List[Tuple[str, Exception]] = []

        for name in reversed(initialized):
            try:
                self._components[name].close()
            except Exception as exc:
                failures.append((name, exc))

        with self._lock:
            self._initialized = []
            self._state = "stopped"

        if failures:
            details = "; ".join(
                f"{name}: {error}" for name, error in failures
            )

            raise LifecycleError(
                f"Shutdown completed with errors: {details}",
                failures,
            )

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "registered_components": list(self._components),
                "initialized_components": list(self._initialized),
            }
