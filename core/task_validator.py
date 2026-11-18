"""Comprehensive task validation for Omi Vanguard AI."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from typing import Any, Dict, List, Optional, Set


class TaskValidationError(ValueError):
    """Raised when a task plan fails validation."""

    def __init__(self, errors: List[str]):
        self.errors = list(errors)
        message = "Task validation failed:\n" + "\n".join(
            f"- {error}" for error in self.errors
        )
        super().__init__(message)


class TaskValidator:
    """
    Validates TaskPlan objects before execution.

    Expected task attributes:
        task_id
        steps
        requires_confirmation (optional)

    Expected step attributes:
        step_id
        action
        parameters
        dependencies
        retry_count
        max_retries
    """

    def __init__(
        self,
        operation_registry: Optional[Any] = None,
        supported_platforms: Optional[Iterable[Any]] = None,
    ):
        self.operation_registry = operation_registry

        self.supported_platforms = (
            self._normalize_platforms(supported_platforms)
            if supported_platforms is not None
            else None
        )

    @staticmethod
    def _platform_value(platform: Any) -> str:
        """Convert a platform enum or string to a normalized value."""
        value = getattr(platform, "value", platform)

        if not isinstance(value, str):
            raise ValueError("Platform must be a string or string enum.")

        value = value.strip().lower()

        if not value:
            raise ValueError("Platform cannot be empty.")

        return value

    @classmethod
    def _normalize_platforms(
        cls,
        platforms: Iterable[Any],
    ) -> Set[str]:
        if isinstance(platforms, (str, bytes)):
            raise ValueError(
                "supported_platforms must be an iterable of platforms, "
                "not a single string."
            )

        try:
            return {cls._platform_value(item) for item in platforms}
        except TypeError as exc:
            raise ValueError(
                "supported_platforms must be iterable."
            ) from exc

    def validate(
        self,
        task: Any,
        check_registry: bool = False,
        platform: Optional[Any] = None,
        raise_exception: bool = True,
    ) -> bool:
        """Validate a task and optionally raise TaskValidationError."""

        errors: List[str] = []

        if task is None:
            return self._finish(
                ["Task cannot be None."],
                raise_exception,
            )

        task_id = getattr(task, "task_id", None)

        if not isinstance(task_id, str) or not task_id.strip():
            errors.append(
                "Task must have a non-empty string task_id."
            )

        steps = getattr(task, "steps", None)

        if not isinstance(steps, list):
            errors.append("Task steps must be a list.")
            return self._finish(errors, raise_exception)

        if not steps:
            errors.append("Task must contain at least one step.")
            return self._finish(errors, raise_exception)

        step_ids: Set[str] = set()
        valid_steps = []

        # Validate each step.
        for index, step in enumerate(steps):
            if step is None:
                errors.append(
                    f"Step at position {index} cannot be None."
                )
                continue

            step_id = getattr(step, "step_id", None)

            if not isinstance(step_id, str) or not step_id.strip():
                errors.append(
                    f"Step at position {index} has an invalid step_id."
                )
                continue

            if step_id in step_ids:
                errors.append(
                    f"Duplicate step_id: {step_id}"
                )
            else:
                step_ids.add(step_id)

            valid_steps.append(step)

            action = getattr(step, "action", None)

            if not isinstance(action, str) or not action.strip():
                errors.append(
                    f"Step '{step_id}' must have a valid action."
                )
            elif check_registry:
                self._validate_operation(
                    action,
                    step_id,
                    errors,
                )

            parameters = getattr(step, "parameters", None)

            if not isinstance(parameters, Mapping):
                errors.append(
                    f"Step '{step_id}' parameters must be a mapping."
                )

            dependencies = getattr(step, "dependencies", None)

            if not isinstance(dependencies, list):
                errors.append(
                    f"Step '{step_id}' dependencies must be a list."
                )
            else:
                if any(
                    not isinstance(dep, str) or not dep.strip()
                    for dep in dependencies
                ):
                    errors.append(
                        f"Step '{step_id}' has an invalid dependency."
                    )

                valid_dependencies = [
                    dep for dep in dependencies
                    if isinstance(dep, str)
                ]

                if len(valid_dependencies) != len(set(valid_dependencies)):
                    errors.append(
                        f"Step '{step_id}' contains duplicate dependencies."
                    )

            self._validate_retry_settings(
                step,
                step_id,
                errors,
            )

        # Validate dependency references.
        for step in valid_steps:
            step_id = step.step_id
            dependencies = getattr(step, "dependencies", [])

            if not isinstance(dependencies, list):
                continue

            for dependency in dependencies:
                if not isinstance(dependency, str):
                    continue

                if dependency == step_id:
                    errors.append(
                        f"Step '{step_id}' cannot depend on itself."
                    )
                elif dependency not in step_ids:
                    errors.append(
                        f"Step '{step_id}' depends on unknown step "
                        f"'{dependency}'."
                    )

        # Detect dependency cycles only when references are valid.
        has_invalid_references = any(
            "unknown step" in error
            or "invalid dependency" in error
            or "cannot depend on itself" in error
            or "Duplicate step_id" in error
            for error in errors
        )

        if not has_invalid_references:
            cycle = self._find_cycle(valid_steps)

            if cycle:
                errors.append(
                    "Circular dependency detected: "
                    + " -> ".join(cycle)
                )

        # Validate platform compatibility.
        if platform is not None:
            self._validate_platform(
                valid_steps,
                platform,
                errors,
            )

        # Validate confirmation flag.
        requires_confirmation = getattr(
            task,
            "requires_confirmation",
            False,
        )

        if not isinstance(requires_confirmation, bool):
            errors.append(
                "Task requires_confirmation must be a boolean."
            )

        return self._finish(errors, raise_exception)

    def _validate_operation(
        self,
        action: str,
        step_id: str,
        errors: List[str],
    ) -> None:
        """Validate operation registration and enabled state."""

        if self.operation_registry is None:
            errors.append(
                "Registry validation requested, but no operation "
                "registry was provided."
            )
            return

        try:
            if not self.operation_registry.exists(action):
                errors.append(
                    f"Step '{step_id}' uses unregistered operation "
                    f"'{action}'."
                )
                return

            definition = self.operation_registry.get(action)

            if not getattr(definition, "enabled", False):
                errors.append(
                    f"Operation '{action}' is disabled."
                )

        except Exception as exc:
            errors.append(
                f"Could not validate operation '{action}': {exc}"
            )

    @staticmethod
    def _validate_retry_settings(
        step: Any,
        step_id: str,
        errors: List[str],
    ) -> None:
        retry_count = getattr(step, "retry_count", 0)
        max_retries = getattr(step, "max_retries", 0)

        valid_retry = (
            isinstance(retry_count, int)
            and not isinstance(retry_count, bool)
            and retry_count >= 0
        )

        valid_max = (
            isinstance(max_retries, int)
            and not isinstance(max_retries, bool)
            and max_retries >= 0
        )

        if not valid_retry:
            errors.append(
                f"Step '{step_id}' retry_count must be a "
                "non-negative integer."
            )

        if not valid_max:
            errors.append(
                f"Step '{step_id}' max_retries must be a "
                "non-negative integer."
            )

        if valid_retry and valid_max and retry_count > max_retries:
            errors.append(
                f"Step '{step_id}' retry_count cannot exceed max_retries."
            )

    def _validate_platform(
        self,
        steps: list,
        platform: Any,
        errors: List[str],
    ) -> None:
        """Validate global and operation-specific platform support."""

        try:
            platform_value = self._platform_value(platform)
        except ValueError as exc:
            errors.append(str(exc))
            return

        # Validate against globally supported platforms.
        if (
            self.supported_platforms is not None
            and platform_value not in self.supported_platforms
        ):
            errors.append(
                f"Platform '{platform_value}' is not supported by "
                "this TaskValidator."
            )
            return

        # Operation-specific validation requires a registry.
        if self.operation_registry is None:
            return

        for step in steps:
            action = getattr(step, "action", None)

            if not isinstance(action, str) or not action.strip():
                continue

            try:
                if not self.operation_registry.exists(action):
                    continue

                definition = self.operation_registry.get(action)

                supported = getattr(
                    definition,
                    "supported_platforms",
                    None,
                )

                # Empty or None means no platform restriction is declared.
                if supported is None:
                    continue

                if isinstance(supported, (str, bytes)):
                    supported_values = {
                        self._platform_value(supported)
                    }
                else:
                    supported_values = self._normalize_platforms(
                        supported
                    )

                if (
                    supported_values
                    and platform_value not in supported_values
                ):
                    errors.append(
                        f"Operation '{action}' does not support "
                        f"platform '{platform_value}'."
                    )

            except Exception as exc:
                errors.append(
                    f"Platform validation failed for operation "
                    f"'{action}': {exc}"
                )

    @staticmethod
    def _find_cycle(steps: list) -> Optional[List[str]]:
        """
        Detect dependency cycles using Kahn's algorithm.

        Returns a list of involved step IDs when a cycle exists.
        """

        graph: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = {}

        for step in steps:
            step_id = getattr(step, "step_id", None)

            if not isinstance(step_id, str):
                continue

            in_degree[step_id] = 0

        for step in steps:
            step_id = getattr(step, "step_id", None)
            dependencies = getattr(step, "dependencies", [])

            if (
                not isinstance(step_id, str)
                or not isinstance(dependencies, list)
            ):
                continue

            for dependency in dependencies:
                if (
                    isinstance(dependency, str)
                    and dependency in in_degree
                ):
                    # Dependency must execute before this step.
                    graph[dependency].append(step_id)
                    in_degree[step_id] += 1

        queue = deque(
            node
            for node, degree in in_degree.items()
            if degree == 0
        )

        processed = 0

        while queue:
            node = queue.popleft()
            processed += 1

            for dependent in graph[node]:
                in_degree[dependent] -= 1

                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if processed == len(in_degree):
            return None

        return [
            node
            for node, degree in in_degree.items()
            if degree > 0
        ]

    @staticmethod
    def _finish(
        errors: List[str],
        raise_exception: bool,
    ) -> bool:
        if errors and raise_exception:
            raise TaskValidationError(errors)

        return not errors

    def validate_or_raise(
        self,
        task: Any,
        **kwargs: Any,
    ) -> None:
        """Validate a task or raise TaskValidationError."""

        self.validate(
            task,
            raise_exception=True,
            **kwargs,
        )

    def get_validation_errors(
        self,
        task: Any,
        **kwargs: Any,
    ) -> List[str]:
        """Return validation errors without raising an exception."""

        try:
            self.validate(
                task,
                raise_exception=True,
                **kwargs,
            )
            return []

        except TaskValidationError as exc:
            return list(exc.errors)
