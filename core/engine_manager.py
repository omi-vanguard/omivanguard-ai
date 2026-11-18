"""Coordinates manager registration and lifecycle for Omi Vanguard."""

from collections import deque
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

try:
    from .lifecycle import LifecycleError, LifecycleManager
except ImportError:
    from lifecycle import LifecycleError, LifecycleManager


class EngineManagerError(RuntimeError):
    """Raised when engine-manager coordination fails."""


class EngineManager:
    """Registers, initializes, accesses, and shuts down engine managers."""

    def __init__(self, engine: Any) -> None:
        if engine is None:
            raise TypeError("engine cannot be None")
        if not callable(getattr(engine, "register_manager", None)):
            raise TypeError(
                "engine must provide register_manager(name, manager)"
            )

        self._engine = engine
        self._lock = RLock()
        self._managers: Dict[str, Any] = {}
        self._dependencies: Dict[str, Tuple[str, ...]] = {}
        self._lifecycle = LifecycleManager()
        self._initialized = False
        self._initializing = False

    def register_manager(
        self,
        name: str,
        manager: Any,
        depends_on: Optional[List[str]] = None,
    ) -> None:
        """Register a manager and its startup dependencies."""

        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")

        if manager is None:
            raise TypeError("manager cannot be None")

        if not callable(getattr(manager, "initialize", None)):
            raise TypeError(f"Manager '{name}' must provide initialize()")

        if not callable(getattr(manager, "close", None)):
            raise TypeError(f"Manager '{name}' must provide close()")

        if depends_on is None:
            dependencies = ()
        else:
            if not isinstance(depends_on, (list, tuple)):
                raise TypeError("depends_on must be a list, tuple, or None")

            if any(
                not isinstance(item, str) or not item.strip()
                for item in depends_on
            ):
                raise ValueError(
                    "Dependency names must be non-empty strings"
                )

            dependencies = tuple(dict.fromkeys(depends_on))

        with self._lock:
            if self._initialized or self._initializing:
                raise EngineManagerError(
                    "Managers can only be registered before initialization"
                )

            if name in self._managers:
                raise EngineManagerError(
                    f"Manager '{name}' is already registered"
                )

            if name in dependencies:
                raise EngineManagerError(
                    f"Manager '{name}' cannot depend on itself"
                )

            self._engine.register_manager(name, manager)
            self._managers[name] = manager
            self._dependencies[name] = dependencies

    def _get_initialization_order(self) -> List[str]:
        """Return a deterministic dependency-respecting order."""

        for name, dependencies in self._dependencies.items():
            missing = [
                dependency
                for dependency in dependencies
                if dependency not in self._managers
            ]

            if missing:
                raise EngineManagerError(
                    f"Manager '{name}' has unknown dependencies: {missing}"
                )

        indegree = {
            name: 0 for name in self._managers
        }

        dependents = {
            name: [] for name in self._managers
        }

        for name, dependencies in self._dependencies.items():
            indegree[name] = len(dependencies)

            for dependency in dependencies:
                dependents[dependency].append(name)

        ready = deque(
            name
            for name in self._managers
            if indegree[name] == 0
        )

        order = []

        while ready:
            current = ready.popleft()
            order.append(current)

            for dependent in dependents[current]:
                indegree[dependent] -= 1

                if indegree[dependent] == 0:
                    ready.append(dependent)

        if len(order) != len(self._managers):
            cyclic = [
                name
                for name, count in indegree.items()
                if count > 0
            ]

            raise EngineManagerError(
                f"Manager dependency cycle detected: {cyclic}"
            )

        return order

    def initialize(self) -> None:
        """Initialize managers in dependency order."""

        with self._lock:
            if self._initialized:
                return

            if self._initializing:
                raise EngineManagerError(
                    "Manager initialization is already running"
                )

            self._initializing = True

        try:
            order = self._get_initialization_order()

            for name in order:
                self._lifecycle.register(
                    name,
                    self._managers[name],
                )

            self._lifecycle.initialize()

            with self._lock:
                self._initialized = True

        except Exception:
            # A failed startup must not leave duplicate lifecycle entries
            # that prevent a later initialization retry.
            self._lifecycle = LifecycleManager()
            raise

        finally:
            with self._lock:
                self._initializing = False

    def shutdown(self) -> None:
        """Shut down managers in reverse dependency order."""

        with self._lock:
            if not self._initialized:
                return

        try:
            self._lifecycle.shutdown()
        finally:
            with self._lock:
                self._initialized = False

    def close(self) -> None:
        """Close managers; compatible with the BaseManager interface."""
        self.shutdown()

    def get_manager(self, name: str) -> Any:
        """Return a registered manager by name."""

        with self._lock:
            try:
                return self._managers[name]
            except KeyError as exc:
                raise EngineManagerError(
                    f"Manager '{name}' is not registered"
                ) from exc

    def list_managers(self) -> List[str]:
        with self._lock:
            return list(self._managers)

    def get_status(self) -> Dict[str, Any]:
        """Return manager and lifecycle status."""

        with self._lock:
            return {
                "initialized": self._initialized,
                "initializing": self._initializing,
                "manager_count": len(self._managers),
                "managers": list(self._managers),
                "dependencies": {
                    name: list(dependencies)
                    for name, dependencies in self._dependencies.items()
                },
                "lifecycle": self._lifecycle.get_status(),
      }
