"""
Omi Vanguard AI
Core Interfaces
Version: 2.1.0

Defines standard contracts for spreadsheet backends
and engine managers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

try:
    from ..models import (
        OperationResult,
        FeatureCapability,
        SpreadsheetPlatform,
        Status,
    )
except ImportError:
    from models import (
        OperationResult,
        FeatureCapability,
        SpreadsheetPlatform,
        Status,
    )


# =========================================================
# TYPE DEFINITIONS
# =========================================================

FilePath = str | Path


# =========================================================
# BACKEND INTERFACE
# =========================================================

class BaseBackend(ABC):
    """
    Base contract for Excel and Google Sheets backends.

    Every backend must implement execute().
    """

    @abstractmethod
    def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
    ) -> OperationResult:
        """Execute a spreadsheet operation."""
        raise NotImplementedError

    @abstractmethod
    def get_platform(self) -> SpreadsheetPlatform:
        """Return the platform supported by this backend."""
        raise NotImplementedError

    def get_feature_capability(
        self,
        feature_name: str,
    ) -> Optional[FeatureCapability]:
        """
        Return feature support information.

        Backends may override this method.
        """
        return None

    def initialize(self) -> None:
        """Initialize backend resources when required."""

    def close(self) -> None:
        """Release backend resources when required."""

    def get_status(self) -> dict[str, Any]:
        """Return backend status information."""
        return {
            "backend": type(self).__name__,
            "platform": self.get_platform().value,
            "initialized": True,
        }


# =========================================================
# BASE MANAGER INTERFACE
# =========================================================

class BaseManager(ABC):
    """
    Common contract for engine managers.

    Managers handle specialized responsibilities such as
    workbook validation, backup, security and history.
    """

    @abstractmethod
    def initialize(self) -> None:
        """Initialize manager resources."""
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """Return manager status information."""
        raise NotImplementedError

    def close(self) -> None:
        """Release manager resources when required."""


# =========================================================
# WORKBOOK MANAGER INTERFACE
# =========================================================

class WorkbookManagerInterface(BaseManager):
    """Contract for workbook validation and verification."""

    @abstractmethod
    def validate_file(self, file_path: FilePath) -> Any:
        """Validate an input workbook."""
        raise NotImplementedError

    @abstractmethod
    def verify_output(self, file_path: FilePath) -> Any:
        """Verify a generated workbook."""
        raise NotImplementedError


# =========================================================
# BACKUP MANAGER INTERFACE
# =========================================================

class BackupManagerInterface(BaseManager):
    """Contract for backup and restoration."""

    @abstractmethod
    def create_backup(self, file_path: FilePath) -> Any:
        """Create a backup before modifying a file."""
        raise NotImplementedError

    @abstractmethod
    def restore_backup(self, backup_id: str) -> Any:
        """Restore a previously created backup."""
        raise NotImplementedError

    @abstractmethod
    def verify_backup(self, backup_id: str) -> bool:
        """Verify backup integrity."""
        raise NotImplementedError


# =========================================================
# SECURITY MANAGER INTERFACE
# =========================================================

class SecurityManagerInterface(BaseManager):
    """Contract for access control and permission checks."""

    @abstractmethod
    def check_permission(
        self,
        principal: str,
        action: str,
        resource: Optional[FilePath] = None,
    ) -> bool:
        """Check whether a principal may perform an action."""
        raise NotImplementedError


# =========================================================
# HISTORY MANAGER INTERFACE
# =========================================================

class HistoryManagerInterface(BaseManager):
    """Contract for operation and task history."""

    @abstractmethod
    def record_operation(
        self,
        operation: str,
        result: OperationResult,
        status: Status,
        principal: str,
    ) -> Any:
        """Record an operation execution."""
        raise NotImplementedError

    @abstractmethod
    def record_task(
        self,
        task: Any,
        report: Any,
    ) -> Any:
        """Record a task execution report."""
        raise NotImplementedError


# =========================================================
# EVENT LISTENER INTERFACE
# =========================================================

class EventListener(Protocol):
    """Protocol for optional engine event listeners."""

    def on_event(
        self,
        event_name: str,
        event_data: dict[str, Any],
    ) -> None:
        """Receive an engine event."""
        ...


# =========================================================
# HEALTH CHECK INTERFACE
# =========================================================

class HealthCheckInterface(ABC):
    """Contract for component health checks."""

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Return component health information."""
        raise NotImplementedError


# =========================================================
# INTERFACE VALIDATION
# =========================================================

def validate_backend(backend: Any) -> bool:
    """Check whether an object implements the backend contract."""

    required_methods = (
        "execute",
        "get_platform",
    )

    return all(
        callable(getattr(backend, method, None))
        for method in required_methods
    )


def validate_manager(manager: Any) -> bool:
    """Check whether an object implements the base manager contract."""

    required_methods = (
        "initialize",
        "get_status",
    )

    return all(
        callable(getattr(manager, method, None))
        for method in required_methods
    )


def validate_manager_method(
    manager: Any,
    method_name: str,
) -> bool:
    """Check whether a manager provides a specific method."""

    return callable(
        getattr(manager, method_name, None)
    )
