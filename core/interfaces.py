"""
Omi Vanguard AI
Core Interfaces

Shared structural interfaces for core components.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class SpreadsheetBackend(Protocol):
    """Interface for Excel and Google Sheets backends."""

    def execute(
        self,
        operation: str,
        parameters: Mapping[str, Any],
    ) -> Any:
        """Execute a spreadsheet operation."""
        ...


@runtime_checkable
class SecurityManager(Protocol):
    """Interface for permission checks."""

    def check_permission(
        self,
        *,
        principal: str,
        action: str,
        resource: str | None = None,
    ) -> bool:
        """Check whether an action is permitted."""
        ...


@runtime_checkable
class WorkbookManager(Protocol):
    """Interface for workbook validation and verification."""

    def validate_file(self, file_path: str) -> Any:
        ...

    def verify_output(self, output_path: str) -> Any:
        ...


@runtime_checkable
class BackupManager(Protocol):
    """Interface for backup and recovery operations."""

    def create_backup(self, file_path: str | None) -> Any:
        ...

    def restore_backup(self, backup_id: str) -> Any:
        ...


@runtime_checkable
class HistoryManager(Protocol):
    """Interface for execution history."""

    def record_operation(
        self,
        *,
        operation: str,
        result: Any,
        status: Any,
        principal: str,
    ) -> Any:
        ...

    def record_task(
        self,
        *,
        task: Any,
        report: Any,
    ) -> Any:
        ...
