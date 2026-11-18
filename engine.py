"""
Omi Vanguard AI
Core Spreadsheet Engine
Version: 2.1.0

Central controller for Excel and Google Sheets operations.
Specialized functionality belongs in separate modules.
"""

from __future__ import annotations

import threading
import uuid

from typing import Any, Callable, Optional

try:
    from .errors import (
        OmiExcelError,
        ValidationError,
        ConfigurationError,
        UnsupportedFeatureError,
        SecurityError,
    )

    from .models import (
        EngineConfig,
        OperationResult,
        TaskPlan,
        TaskExecutionReport,
        SpreadsheetPlatform,
        Status,
        FeatureCapability,
        FeatureSupport,
        utc_now,
    )

except ImportError:
    from errors import (
        OmiExcelError,
        ValidationError,
        ConfigurationError,
        UnsupportedFeatureError,
        SecurityError,
    )

    from models import (
        EngineConfig,
        OperationResult,
        TaskPlan,
        TaskExecutionReport,
        SpreadsheetPlatform,
        Status,
        FeatureCapability,
        FeatureSupport,
        utc_now,
    )


VERSION = "2.1.0"


class OmiVanguardEngine:
    """
    Main orchestration controller.

    Responsibilities:
    - Backend registration
    - Manager integration
    - Operation execution
    - Task dependency management
    - Retry and error handling
    - Pause, resume and cancellation
    - Backup, security and history integration
    - Feature capability checking
    """

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
    ):
        self.config = config or EngineConfig()

        self.backends: dict[str, Any] = {}
        self.managers: dict[str, Any] = {}

        self.operation_handlers: dict[str, Callable] = {}

        self.active_tasks: dict[str, TaskExecutionReport] = {}
        self.task_controls: dict[str, dict] = {}

        self.last_error: Optional[str] = None

        self._lock = threading.RLock()
        self._cancel_event = threading.Event()

        self._validate_config()

    # -----------------------------------------------------
    # CONFIGURATION
    # -----------------------------------------------------

    def _validate_config(self) -> None:
        if self.config.max_file_size_mb <= 0:
            raise ConfigurationError(
                "max_file_size_mb must be positive."
            )

        if self.config.timeout_seconds <= 0:
            raise ConfigurationError(
                "timeout_seconds must be positive."
            )

    # -----------------------------------------------------
    # BACKEND REGISTRATION
    # -----------------------------------------------------

    def register_backend(
        self,
        platform: SpreadsheetPlatform,
        backend: Any,
    ) -> None:
        if not isinstance(platform, SpreadsheetPlatform):
            raise ValidationError("Invalid spreadsheet platform.")

        if backend is None:
            raise ValidationError("Backend cannot be None.")

        with self._lock:
            self.backends[platform.value] = backend

    def get_backend(
        self,
        platform: SpreadsheetPlatform,
    ) -> Any:
        backend = self.backends.get(platform.value)

        if backend is None:
            raise UnsupportedFeatureError(
                f"No backend registered for {platform.value}."
            )

        return backend

    def unregister_backend(
        self,
        platform: SpreadsheetPlatform,
    ) -> bool:
        with self._lock:
            return (
                self.backends.pop(platform.value, None)
                is not None
            )

    # -----------------------------------------------------
    # MANAGER INTEGRATION
    # -----------------------------------------------------

    def register_manager(
        self,
        name: str,
        manager: Any,
    ) -> None:
        if not name or manager is None:
            raise ValidationError(
                "A manager name and instance are required."
            )

        with self._lock:
            self.managers[name] = manager

    def get_manager(self, name: str) -> Any:
        manager = self.managers.get(name)

        if manager is None:
            raise UnsupportedFeatureError(
                f"Manager not registered: {name}."
            )

        return manager

    def unregister_manager(self, name: str) -> bool:
        with self._lock:
            return self.managers.pop(name, None) is not None

    # -----------------------------------------------------
    # OPERATION REGISTRATION
    # -----------------------------------------------------

    def register_operation(
        self,
        name: str,
        handler: Callable,
    ) -> None:
        if not name or not callable(handler):
            raise ValidationError(
                "A valid operation name and handler are required."
            )

        with self._lock:
            self.operation_handlers[name] = handler

    def unregister_operation(self, name: str) -> bool:
        with self._lock:
            return (
                self.operation_handlers.pop(name, None)
                is not None
            )

    # -----------------------------------------------------
    # INTEGRATION HELPERS
    # -----------------------------------------------------

    def _call_manager(
        self,
        manager_name: str,
        method_name: str,
        *args,
        **kwargs,
    ):
        manager = self.managers.get(manager_name)

        if manager is None:
            return None

        method = getattr(manager, method_name, None)

        if not callable(method):
            raise UnsupportedFeatureError(
                f"{manager_name} does not implement {method_name}()."
            )

        return method(*args, **kwargs)

    def _check_security(
        self,
        operation: str,
        parameters: dict,
        principal: str,
    ) -> None:
        modifies_file = bool(
            parameters.get("modifies_file", False)
        )

        if self.config.read_only and modifies_file:
            raise SecurityError(
                "Engine is in read-only mode."
            )

        security = self.managers.get("security")

        if security is not None:
            checker = getattr(
                security,
                "check_permission",
                None,
            )

            if not callable(checker):
                raise UnsupportedFeatureError(
                    "Security manager must implement check_permission()."
                )

            allowed = checker(
                principal=principal,
                action="write" if modifies_file else "read",
                resource=parameters.get("file_path"),
            )

            if not allowed:
                raise SecurityError(
                    "Permission denied."
                )

    # -----------------------------------------------------
    # OPERATION EXECUTION
    # -----------------------------------------------------

    def execute_operation(
        self,
        operation: str,
        parameters: Optional[dict] = None,
        platform: Optional[SpreadsheetPlatform] = None,
        principal: str = "system",
    ) -> OperationResult:

        parameters = dict(parameters or {})
        operation_id = uuid.uuid4().hex
        started_at = utc_now()

        backup_info = None

        try:
            if self._cancel_event.is_set():
                raise OmiExcelError(
                    "Engine cancellation requested."
                )

            self._check_security(
                operation,
                parameters,
                principal,
            )

            modifies_file = bool(
                parameters.get("modifies_file", False)
            )

            file_path = parameters.get("file_path")

            # Delegate file validation to the workbook manager.
            if file_path:
                self._call_manager(
                    "workbook",
                    "validate_file",
                    file_path,
                )

            # Delegate backup creation to backup manager.
            if modifies_file and self.config.create_backup:
                backup_info = self._call_manager(
                    "backup",
                    "create_backup",
                    file_path,
                )

            handler = self.operation_handlers.get(operation)

            if handler is not None:
                result = handler(parameters)

            else:
                if platform is None:
                    raise UnsupportedFeatureError(
                        f"No handler or platform supplied for {operation}."
                    )

                backend = self.get_backend(platform)

                executor = getattr(
                    backend,
                    "execute",
                    None,
                )

                if not callable(executor):
                    raise UnsupportedFeatureError(
                        "Backend must implement execute()."
                    )

                result = executor(
                    operation,
                    parameters,
                )

            if not isinstance(result, OperationResult):
                raise ValidationError(
                    "Operation handler must return OperationResult."
                )

            if not result.success:
                raise OmiExcelError(
                    result.message or "Operation failed."
                )

            # Verify output through the relevant manager.
            if result.output_path and self.config.verify_output:
                self._call_manager(
                    "workbook",
                    "verify_output",
                    result.output_path,
                )

            result.operation_id = operation_id
            result.started_at = started_at
            result.completed_at = utc_now()

            self._record_history(
                operation,
                result,
                Status.SUCCESS,
                principal,
            )

            return result

        except Exception as exc:
            self.last_error = str(exc)

            # Delegate recovery to backup manager.
            if (
                backup_info is not None
                and self.config.enable_rollback
            ):
                try:
                    self._call_manager(
                        "backup",
                        "restore_backup",
                        backup_info.backup_id,
                    )
                except Exception as recovery_error:
                    self.last_error = (
                        f"{exc}; recovery failed: {recovery_error}"
                    )

            failed_result = OperationResult(
                success=False,
                operation=operation,
                message=str(exc),
                errors=[str(exc)],
                operation_id=operation_id,
                started_at=started_at,
                completed_at=utc_now(),
            )

            self._record_history(
                operation,
                failed_result,
                Status.FAILED,
                principal,
            )

            return failed_result

    # -----------------------------------------------------
    # HISTORY INTEGRATION
    # -----------------------------------------------------

    def _record_history(
        self,
        operation: str,
        result: OperationResult,
        status: Status,
        principal: str,
    ) -> None:
        history = self.managers.get("history")

        if history is not None:
            recorder = getattr(
                history,
                "record_operation",
                None,
            )

            if callable(recorder):
                recorder(
                    operation=operation,
                    result=result,
                    status=status,
                    principal=principal,
                )

    # -----------------------------------------------------
    # TASK DEPENDENCY VALIDATION
    # -----------------------------------------------------

    def validate_task_dependencies(
        self,
        task: TaskPlan,
    ) -> bool:

        step_ids = [
            step.step_id
            for step in task.steps
        ]

        if len(step_ids) != len(set(step_ids)):
            raise ValidationError(
                "Duplicate task step IDs."
            )

        graph = {
            step.step_id: set(step.dependencies)
            for step in task.steps
        }

        for step_id, dependencies in graph.items():
            missing = dependencies - set(step_ids)

            if missing:
                raise ValidationError(
                    f"Missing dependencies in {step_id}: "
                    f"{sorted(missing)}"
                )

        visiting = set()
        visited = set()

        def visit(node):
            if node in visiting:
                raise ValidationError(
                    "Circular task dependency detected."
                )

            if node in visited:
                return

            visiting.add(node)

            for dependency in graph[node]:
                visit(dependency)

            visiting.remove(node)
            visited.add(node)

        for step_id in graph:
            visit(step_id)

        return True

    # -----------------------------------------------------
    # TASK CONTROLS
    # -----------------------------------------------------

    def pause_task(self, task_id: str) -> bool:
        control = self.task_controls.get(task_id)

        if control is None:
            raise ValidationError("Task is not active.")

        control["pause"].clear()
        return True

    def resume_task(self, task_id: str) -> bool:
        control = self.task_controls.get(task_id)

        if control is None:
            raise ValidationError("Task is not active.")

        control["pause"].set()
        return True

    def cancel_task(self, task_id: str) -> bool:
        control = self.task_controls.get(task_id)

        if control is None:
            raise ValidationError("Task is not active.")

        control["cancel"].set()
        return True

    def _wait_for_task(self, control) -> bool:
        while not control["pause"].is_set():
            if control["cancel"].is_set():
                return False

            time_wait = threading.Event()
            time_wait.wait(0.1)

        return not control["cancel"].is_set()

    # -----------------------------------------------------
    # TASK EXECUTION
    # -----------------------------------------------------

    def execute_task(
        self,
        task: TaskPlan,
        platform: Optional[SpreadsheetPlatform] = None,
        principal: str = "system",
        confirmed: bool = False,
    ) -> TaskExecutionReport:

        self.validate_task_dependencies(task)

        if task.requires_confirmation and not confirmed:
            raise SecurityError(
                "Task requires confirmation before execution."
            )

        report = TaskExecutionReport(
            task_id=task.task_id,
            status=Status.RUNNING,
            total_steps=len(task.steps),
            started_at=utc_now(),
        )

        control = {
            "pause": threading.Event(),
            "cancel": threading.Event(),
        }

        control["pause"].set()

        with self._lock:
            if task.task_id in self.active_tasks:
                raise ValidationError(
                    "Task is already running."
                )

            self.active_tasks[task.task_id] = report
            self.task_controls[task.task_id] = control

        task.status = Status.RUNNING

        completed = set()
        pending = {
            step.step_id: step
            for step in task.steps
        }

        try:
            while pending:

                if self._cancel_event.is_set():
                    report.status = Status.CANCELLED
                    break

                if not self._wait_for_task(control):
                    report.status = Status.CANCELLED
                    break

                ready_steps = [
                    step
                    for step in pending.values()
                    if set(step.dependencies).issubset(completed)
                ]

                if not ready_steps:
                    raise ValidationError(
                        "Task dependency execution is blocked."
                    )

                step = ready_steps[0]
                step.status = Status.RUNNING

                success = False
                attempts = 0

                while attempts <= step.max_retries:
                    if not self._wait_for_task(control):
                        break

                    attempts += 1

                    result = self.execute_operation(
                        operation=step.action,
                        parameters=step.parameters,
                        platform=platform,
                        principal=principal,
                    )

                    step.result = result
                    report.results.append(result)

                    if result.success:
                        success = True
                        break

                    step.retry_count += 1

                if success:
                    step.status = Status.SUCCESS
                    completed.add(step.step_id)

                    report.completed_steps += 1
                    pending.pop(step.step_id)

                else:
                    step.status = Status.FAILED
                    report.failed_steps += 1
                    pending.pop(step.step_id)

                    break

            if report.status != Status.CANCELLED:
                if report.failed_steps:
                    report.status = Status.PARTIAL
                elif report.completed_steps == report.total_steps:
                    report.status = Status.SUCCESS
                else:
                    report.status = Status.FAILED

            task.status = report.status

        except Exception as exc:
            self.last_error = str(exc)

            report.status = Status.FAILED
            task.status = Status.FAILED

        finally:
            report.completed_at = utc_now()
            task.completed_at = utc_now()

            with self._lock:
                self.active_tasks.pop(task.task_id, None)
                self.task_controls.pop(task.task_id, None)

            self._call_manager(
                "history",
                "record_task",
                task=task,
                report=report,
            )

        return report

    # -----------------------------------------------------
    # ENGINE CANCELLATION
    # -----------------------------------------------------

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        self._cancel_event.clear()

    # -----------------------------------------------------
    # FEATURE CAPABILITY
    # -----------------------------------------------------

    def check_feature(
        self,
        feature_name: str,
        platform: SpreadsheetPlatform,
    ) -> FeatureCapability:

        backend = self.backends.get(platform.value)

        if backend is None:
            return FeatureCapability(
                feature_name=feature_name,
                platform=platform,
                support=FeatureSupport.UNKNOWN,
                limitations=["Backend is not registered."],
            )

        checker = getattr(
            backend,
            "get_feature_capability",
            None,
        )

        if callable(checker):
            capability = checker(feature_name)

            if isinstance(capability, FeatureCapability):
                return capability

        return FeatureCapability(
            feature_name=feature_name,
            platform=platform,
            support=FeatureSupport.UNKNOWN,
            backend=type(backend).__name__,
            limitations=[
                "Backend has not declared feature support."
            ],
        )

    # -----------------------------------------------------
    # ENGINE STATUS
    # -----------------------------------------------------

    def get_status(self) -> dict:
        with self._lock:
            return {
                "name": "Omi Vanguard AI",
                "version": VERSION,
                "backends": list(self.backends.keys()),
                "managers": list(self.managers.keys()),
                "operations": list(
                    self.operation_handlers.keys()
                ),
                "active_tasks": len(self.active_tasks),
                "read_only": self.config.read_only,
                "last_error": self.last_error,
            }


# =========================================================
# DEFAULT ENGINE
# =========================================================

engine = OmiVanguardEngine()
