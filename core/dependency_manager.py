"""Dependency management for Omi Vanguard AI."""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Set


class DependencyError(ValueError):
    """Raised when task dependency configuration is invalid."""


class DependencyManager:
    """
    Manages task step dependencies and execution ordering.

    Expected task:
        task.steps

    Expected step:
        step.step_id
        step.dependencies
    """

    @staticmethod
    def _build_graph(task: Any):
        """Build and validate the task dependency graph."""

        steps = getattr(task, "steps", None)

        if not isinstance(steps, list):
            raise DependencyError("Task steps must be a list.")

        by_id: Dict[str, Any] = {}
        order: List[str] = []

        # Validate step IDs and dependency formats.
        for index, step in enumerate(steps):
            if step is None:
                raise DependencyError(
                    f"Step at position {index} cannot be None."
                )

            step_id = getattr(step, "step_id", None)

            if not isinstance(step_id, str) or not step_id.strip():
                raise DependencyError(
                    f"Step at position {index} has an invalid step_id."
                )

            if step_id in by_id:
                raise DependencyError(
                    f"Duplicate step_id: {step_id}"
                )

            dependencies = getattr(step, "dependencies", [])

            if not isinstance(dependencies, list):
                raise DependencyError(
                    f"Step '{step_id}' dependencies must be a list."
                )

            if any(
                not isinstance(dep, str) or not dep.strip()
                for dep in dependencies
            ):
                raise DependencyError(
                    f"Step '{step_id}' has an invalid dependency."
                )

            if len(dependencies) != len(set(dependencies)):
                raise DependencyError(
                    f"Step '{step_id}' contains duplicate dependencies."
                )

            by_id[step_id] = step
            order.append(step_id)

        # Build dependency graph.
        in_degree = {step_id: 0 for step_id in order}
        dependents = {step_id: [] for step_id in order}

        for step_id in order:
            step = by_id[step_id]

            for dependency in step.dependencies:
                if dependency == step_id:
                    raise DependencyError(
                        f"Step '{step_id}' cannot depend on itself."
                    )

                if dependency not in by_id:
                    raise DependencyError(
                        f"Step '{step_id}' depends on unknown step "
                        f"'{dependency}'."
                    )

                in_degree[step_id] += 1
                dependents[dependency].append(step_id)

        return order, by_id, in_degree, dependents

    def get_execution_order(self, task: Any) -> List[Any]:
        """
        Return TaskStep objects in dependency-safe execution order.

        Uses Kahn's topological sorting algorithm.
        Raises DependencyError for invalid or cyclic dependencies.
        """

        order, by_id, in_degree, dependents = (
            self._build_graph(task)
        )

        queue = deque(
            step_id
            for step_id in order
            if in_degree[step_id] == 0
        )

        result: List[str] = []

        while queue:
            step_id = queue.popleft()
            result.append(step_id)

            for dependent in dependents[step_id]:
                in_degree[dependent] -= 1

                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(order):
            cyclic_steps = [
                step_id
                for step_id in order
                if in_degree[step_id] > 0
            ]

            raise DependencyError(
                "Circular dependency detected involving: "
                + ", ".join(cyclic_steps)
            )

        return [by_id[step_id] for step_id in result]

    def get_execution_order_ids(self, task: Any) -> List[str]:
        """Return execution order as step IDs."""

        return [
            step.step_id
            for step in self.get_execution_order(task)
        ]

    def validate_dependencies(self, task: Any) -> bool:
        """Validate dependencies without modifying the task."""

        self.get_execution_order(task)
        return True

    def get_ready_steps(
        self,
        task: Any,
        completed_step_ids: Optional[Set[str]] = None,
    ) -> List[Any]:
        """
        Return steps whose dependencies are all completed.

        Completed steps are excluded from the result.
        """

        completed = set(completed_step_ids or [])

        execution_order = self.get_execution_order(task)

        known_ids = {
            step.step_id
            for step in execution_order
        }

        unknown = completed - known_ids

        if unknown:
            raise DependencyError(
                "Unknown completed step IDs: "
                + ", ".join(sorted(unknown))
            )

        ready = []

        for step in execution_order:
            if step.step_id in completed:
                continue

            dependencies = set(step.dependencies)

            if dependencies.issubset(completed):
                ready.append(step)

        return ready

    def get_dependents(
        self,
        task: Any,
        step_id: str,
        transitive: bool = False,
    ) -> List[Any]:
        """
        Return steps depending on the specified step.

        transitive=False:
            Only direct dependents.

        transitive=True:
            Direct and indirect dependents.
        """

        execution_order = self.get_execution_order(task)

        by_id = {
            step.step_id: step
            for step in execution_order
        }

        if step_id not in by_id:
            raise DependencyError(
                f"Unknown step_id: {step_id}"
            )

        direct_dependents: Dict[str, List[str]] = {
            current_id: []
            for current_id in by_id
        }

        for step in execution_order:
            for dependency in step.dependencies:
                direct_dependents[dependency].append(
                    step.step_id
                )

        result = []
        visited = set()

        queue = deque(direct_dependents[step_id])

        while queue:
            current = queue.popleft()

            if current in visited:
                continue

            visited.add(current)
            result.append(by_id[current])

            if transitive:
                queue.extend(
                    direct_dependents[current]
                )

        return result
