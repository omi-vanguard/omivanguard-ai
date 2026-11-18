"""
Omi Vanguard AI
Operation Registry
Version: 2.1.0

Central registry for spreadsheet operation handlers.
"""

from __future__ import annotations

import threading

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


# =========================================================
# EXCEPTIONS
# =========================================================

class OperationRegistryError(Exception):
    """Base exception for operation registry errors."""


class DuplicateOperationError(OperationRegistryError):
    """Raised when an operation is already registered."""


class OperationNotFoundError(OperationRegistryError):
    """Raised when an operation cannot be found."""


class InvalidOperationError(OperationRegistryError):
    """Raised when an operation definition is invalid."""


# =========================================================
# OPERATION DEFINITION
# =========================================================

@dataclass
class OperationDefinition:
    """Metadata and handler for a registered operation."""

    name: str
    handler: Callable
    description: str = ""
    category: str = "general"
    enabled: bool = True
    requires_confirmation: bool = False
    modifies_file: bool = False
    supported_platforms: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_at: str = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.category = self.category.strip().lower()

        if not self.name:
            raise InvalidOperationError(
                "Operation name cannot be empty."
            )

        if not callable(self.handler):
            raise InvalidOperationError(
                "Operation handler must be callable."
            )

        if not isinstance(self.metadata, dict):
            raise InvalidOperationError(
                "Operation metadata must be a dictionary."
            )

        if not isinstance(self.supported_platforms, tuple):
            self.supported_platforms = tuple(
                self.supported_platforms
            )


# =========================================================
# OPERATION REGISTRY
# =========================================================

class OperationRegistry:
    """
    Thread-safe registry for operation handlers.

    Responsibilities:
    - Register operations
    - Prevent duplicate registrations
    - Retrieve operation definitions
    - Enable and disable operations
    - Remove operations
    - Execute registered handlers
    - List available operations
    """

    def __init__(self) -> None:
        self._operations: dict[
            str, OperationDefinition
        ] = {}

        self._lock = threading.RLock()

    # -----------------------------------------------------
    # NAME VALIDATION
    # -----------------------------------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str):
            raise InvalidOperationError(
                "Operation name must be a string."
            )

        normalized = name.strip().lower()

        if not normalized:
            raise InvalidOperationError(
                "Operation name cannot be empty."
            )

        return normalized

    # -----------------------------------------------------
    # REGISTRATION
    # -----------------------------------------------------

    def register(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        category: str = "general",
        enabled: bool = True,
        requires_confirmation: bool = False,
        modifies_file: bool = False,
        supported_platforms: tuple[str, ...] = (),
        metadata: Optional[dict[str, Any]] = None,
        replace: bool = False,
    ) -> OperationDefinition:
        """Register a new operation."""

        normalized_name = self._normalize_name(name)

        if not callable(handler):
            raise InvalidOperationError(
                "Operation handler must be callable."
            )

        definition = OperationDefinition(
            name=normalized_name,
            handler=handler,
            description=description,
            category=category,
            enabled=enabled,
            requires_confirmation=requires_confirmation,
            modifies_file=modifies_file,
            supported_platforms=tuple(
                supported_platforms
            ),
            metadata=dict(metadata or {}),
        )

        with self._lock:
            if (
                normalized_name in self._operations
                and not replace
            ):
                raise DuplicateOperationError(
                    f"Operation already registered: "
                    f"{normalized_name}"
                )

            self._operations[
                normalized_name
            ] = definition

        return definition

    # -----------------------------------------------------
    # RETRIEVAL
    # -----------------------------------------------------

    def get(
        self,
        name: str,
    ) -> OperationDefinition:
        """Retrieve an operation definition."""

        normalized_name = self._normalize_name(name)

        with self._lock:
            definition = self._operations.get(
                normalized_name
            )

            if definition is None:
                raise OperationNotFoundError(
                    f"Operation not found: {normalized_name}"
                )

            return definition

    def get_handler(
        self,
        name: str,
    ) -> Callable:
        """Retrieve an operation handler."""

        return self.get(name).handler

    def exists(self, name: str) -> bool:
        """Check whether an operation is registered."""

        normalized_name = self._normalize_name(name)

        with self._lock:
            return normalized_name in self._operations

    # -----------------------------------------------------
    # EXECUTION
    # -----------------------------------------------------

    def execute(
        self,
        name: str,
        parameters: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Execute a registered operation handler."""

        definition = self.get(name)

        if not definition.enabled:
            raise InvalidOperationError(
                f"Operation is disabled: {definition.name}"
            )

        parameters = dict(parameters or {})

        return definition.handler(parameters)

    # -----------------------------------------------------
    # ENABLE / DISABLE
    # -----------------------------------------------------

    def enable(self, name: str) -> bool:
        """Enable a registered operation."""

        definition = self.get(name)

        with self._lock:
            definition.enabled = True

        return True

    def disable(self, name: str) -> bool:
        """Disable a registered operation."""

        definition = self.get(name)

        with self._lock:
            definition.enabled = False

        return True

    # -----------------------------------------------------
    # REMOVAL
    # -----------------------------------------------------

    def unregister(self, name: str) -> bool:
        """Remove a registered operation."""

        normalized_name = self._normalize_name(name)

        with self._lock:
            return (
                self._operations.pop(
                    normalized_name,
                    None,
                )
                is not None
            )

    def clear(self) -> None:
        """Remove all registered operations."""

        with self._lock:
            self._operations.clear()

    # -----------------------------------------------------
    # LISTING
    # -----------------------------------------------------

    def list_operations(
        self,
        category: Optional[str] = None,
        enabled_only: bool = False,
    ) -> list[OperationDefinition]:
        """Return registered operations."""

        with self._lock:
            operations = list(
                self._operations.values()
            )

        if category is not None:
            category = category.strip().lower()

            operations = [
                operation
                for operation in operations
                if operation.category == category
            ]

        if enabled_only:
            operations = [
                operation
                for operation in operations
                if operation.enabled
            ]

        return operations

    def list_names(
        self,
        enabled_only: bool = False,
    ) -> list[str]:
        """Return registered operation names."""

        return [
            operation.name
            for operation in self.list_operations(
                enabled_only=enabled_only
            )
        ]

    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return registry status."""

        with self._lock:
            total = len(self._operations)

            enabled = sum(
                1
                for operation in self._operations.values()
                if operation.enabled
            )

            return {
                "total_operations": total,
                "enabled_operations": enabled,
                "disabled_operations": total - enabled,
                "operation_names": list(
                    self._operations.keys()
                ),
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._operations)

    def __contains__(self, name: str) -> bool:
        try:
            return self.exists(name)
        except InvalidOperationError:
            return False


# =========================================================
# DEFAULT REGISTRY
# =========================================================

operation_registry = OperationRegistry()
