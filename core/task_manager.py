"""Omi Vanguard AI - Task Manager.

Coordinates task registration, validation and execution
through the existing OmiVanguardEngine task execution system.
"""

from future import annotations

import threading
from typing import Any, Optional

try:
from ..models import (
Status,
TaskPlan,
TaskExecutionReport,
)
from ..errors import (
OmiExcelError,
ValidationError,
ConfigurationError,
)
from .interfaces import BaseManager
from .operation_registry import (
OperationRegistry,
OperationRegistryError,
InvalidOperationError,
OperationNotFoundError,
)
except ImportError:
from models import (
Status,
TaskPlan,
TaskExecutionReport,
)
from errors import (
OmiExcelError,
ValidationError,
ConfigurationError,
)
from core.interfaces import BaseManager
from core.operation_registry import (
OperationRegistry,
OperationRegistryError,
InvalidOperationError,
OperationNotFoundError,
)

class TaskManagerError(OmiExcelError):
"""Base exception for task manager errors."""

class TaskNotFoundError(TaskManagerError):
"""Raised when a task cannot be found."""

class DuplicateTaskError(TaskManagerError):
"""Raised when a task ID already exists."""

class TaskManager(BaseManager):
"""Manage task plans and delegate execution to the engine."""

def __init__(
    self,
    engine: Any,
    operation_registry: Optional[OperationRegistry] = None,
) -> None:
    if engine is None:
        raise ConfigurationError(
            "An engine instance is required."
        )

    if not callable(
        getattr(engine, "execute_task", None)
    ):
        raise ConfigurationError(
            "Engine must provide execute_task()."
        )

    self.engine = engine
    self.operation_registry = operation_registry

    self._tasks: dict[str, TaskPlan] = {}
    self._reports: dict[str, TaskExecutionReport] = {}
    self._lock = threading.RLock()
    self._initialized = False

# -----------------------------------------------------
# INITIALIZATION
# -----------------------------------------------------

def initialize(self) -> None:
    """Initialize the task manager."""

    with self._lock:
        if self._initialized:
            return

        if self.operation_registry is None:
            self.operation_registry = OperationRegistry()

        self._initialized = True

def close(self) -> None:
    """Release task manager resources."""

    with self._lock:
        self._initialized = False

def _ensure_initialized(self) -> None:
    if not self._initialized:
        self.initialize()

# -----------------------------------------------------
# TASK VALIDATION
# -----------------------------------------------------

@staticmethod
def _validate_task_type(task: TaskPlan) -> None:
    if not isinstance(task, TaskPlan):
        raise ValidationError(
            "Task must be a TaskPlan instance."
        )

    if not isinstance(task.task_id, str) or not task.task_id.strip():
        raise ValidationError(
            "Task ID cannot be empty."
        )

    if not isinstance(task.description, str):
        raise ValidationError(
            "Task description must be a string."
        )

    if not isinstance(task.steps, list):
        raise ValidationError(
            "Task steps must be a list."
        )

    step_ids = set()

    for step in task.steps:
        if not step.step_id or not step.action:
            raise ValidationError(
                "Every task step requires step_id and action."
            )

        if step.step_id in step_ids:
            raise ValidationError(
                f"Duplicate step ID: {step.step_id}"
            )

        step_ids.add(step.step_id)

        if not isinstance(step.parameters, dict):
            raise ValidationError(
                f"Parameters for step {step.step_id} "
                "must be a dictionary."
            )

        if step.max_retries < 0:
            raise ValidationError(
                f"Invalid retry count in step {step.step_id}."
            )

    for step in task.steps:
        for dependency in step.dependencies:
            if dependency not in step_ids:
                raise ValidationError(
                    f"Unknown dependency '{dependency}' "
                    f"in step '{step.step_id}'."
                )

def validate_task(
    self,
    task: TaskPlan,
    check_registry: bool = False,
) -> bool:
    """Validate a task plan and its dependencies."""

    self._validate_task_type(task)

    dependency_validator = getattr(
        self.engine,
        "validate_task_dependencies",
        None,
    )

    if callable(dependency_validator):
        result = dependency_validator(task)

        if result is False:
            raise ValidationError(
                "Task dependency validation failed."
            )

    if check_registry and self.operation_registry is not None:
        for step in task.steps:
            try:
                definition = self.operation_registry.get(
                    step.action
                )
            except OperationNotFoundError as exc:
                raise ValidationError(
                    f"Operation is not registered: {step.action}"
                ) from exc

            if not definition.enabled:
                raise ValidationError(
                    f"Operation is disabled: {step.action}"
                )

    return True

# -----------------------------------------------------
# TASK REGISTRATION
# -----------------------------------------------------

def register_task(
    self,
    task: TaskPlan,
    replace: bool = False,
    check_registry: bool = False,
) -> TaskPlan:
    """Register a task plan."""

    self._ensure_initialized()
    self.validate_task(task, check_registry)

    task_id = task.task_id.strip()

    with self._lock:
        if task_id in self._tasks and not replace:
            raise DuplicateTaskError(
                f"Task already registered: {task_id}"
            )

        self._tasks[task_id] = task

    return task

def get_task(self, task_id: str) -> TaskPlan:
    """Retrieve a registered task."""

    with self._lock:
        task = self._tasks.get(task_id)

        if task is None:
            raise TaskNotFoundError(
                f"Task not found: {task_id}"
            )

        return task

def get_report(
    self,
    task_id: str,
) -> Optional[TaskExecutionReport]:
    """Retrieve the latest execution report."""

    with self._lock:
        return self._reports.get(task_id)

def list_tasks(self) -> list[TaskPlan]:
    """Return all registered tasks."""

    with self._lock:
        return list(self._tasks.values())

def remove_task(self, task_id: str) -> bool:
    """Remove a task that is not currently running."""

    with self._lock:
        task = self._tasks.get(task_id)

        if task is None:
            return False

        if task_id in getattr(
            self.engine,
            "active_tasks",
            {},
        ):
            raise TaskManagerError(
                "Cannot remove a running task."
            )

        del self._tasks[task_id]
        self._reports.pop(task_id, None)

        return True

# -----------------------------------------------------
# TASK EXECUTION
# -----------------------------------------------------

def execute_task(
    self,
    task: str | TaskPlan,
    platform: Optional[str] = None,
    principal: str = "system",
    confirmed: bool = False,
    check_registry: bool = False,
) -> TaskExecutionReport:
    """Execute a registered task through the engine."""

    self._ensure_initialized()

    if isinstance(task, TaskPlan):
        self.register_task(
            task,
            replace=True,
            check_registry=check_registry,
        )
        task_plan = task
    elif isinstance(task, str):
        task_plan = self.get_task(task)
        self.validate_task(
            task_plan,
            check_registry=check_registry,
        )
    else:
        raise ValidationError(
            "Task must be a task ID or TaskPlan."
        )

    if (
        task_plan.requires_confirmation
        and not confirmed
    ):
        raise TaskManagerError(
            "This task requires confirmation before execution."
        )

    report = self.engine.execute_task(
        task_plan,
        platform=platform,
        principal=principal,
        confirmed=confirmed,
    )

    with self._lock:
        self._reports[task_plan.task_id] = report

    return report

# -----------------------------------------------------
# TASK CONTROLS
# -----------------------------------------------------

def pause_task(self, task_id: str) -> bool:
    """Pause a running task."""

    self.get_task(task_id)

    pause = getattr(self.engine, "pause_task", None)

    if not callable(pause):
        raise TaskManagerError(
            "Engine does not support pausing tasks."
        )

    return pause(task_id)

def resume_task(self, task_id: str) -> bool:
    """Resume a paused task."""

    self.get_task(task_id)

    resume = getattr(self.engine, "resume_task", None)

    if not callable(resume):
        raise TaskManagerError(
            "Engine does not support resuming tasks."
        )

    return resume(task_id)

def cancel_task(self, task_id: str) -> bool:
    """Cancel a running task."""

    self.get_task(task_id)

    cancel = getattr(self.engine, "cancel_task", None)

    if not callable(cancel):
        raise TaskManagerError(
            "Engine does not support task cancellation."
        )

    return cancel(task_id)

# -----------------------------------------------------
# STATUS
# -----------------------------------------------------

def get_task_status(self, task_id: str) -> Status:
    """Return the latest known task status."""

    with self._lock:
        report = self._reports.get(task_id)

        if report is not None:
            return report.status

        task = self._tasks.get(task_id)

        if task is None:
            raise TaskNotFoundError(
                f"Task not found: {task_id}"
            )

        return task.status

def get_status(self) -> dict[str, Any]:
    """Return task manager status."""

    with self._lock:
        total = len(self._tasks)

        statuses = {
            status.value: 0
            for status in Status
        }

        for task in self._tasks.values():
            report = self._reports.get(task.task_id)

            current_status = (
                report.status
                if report is not None
                else task.status
            )

            statuses[current_status.value] += 1

        return {
            "manager": type(self).__name__,
            "initialized": self._initialized,
            "total_tasks": total,
            "reported_tasks": len(self._reports),
            "task_statuses": statuses,
            "engine_connected": self.engine is not None,
            "operation_registry_connected": (
                self.operation_registry is not None
            ),
}
