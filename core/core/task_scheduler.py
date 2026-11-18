"""
Omi Vanguard AI
Core Task Scheduler
Version: 2.2.0

Features:
- Delayed task execution
- Date and time scheduling
- Daily and weekly recurring tasks
- Persistent JSON storage
- Job cancellation
- Pause and resume
- Automatic retry
- Execution status tracking
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


# =========================================================
# EXCEPTIONS
# =========================================================

class SchedulerError(Exception):
    """Base scheduler exception."""


class ScheduledJobNotFoundError(SchedulerError):
    """Scheduled job does not exist."""


class SchedulerShutdownError(SchedulerError):
    """Scheduler has been shut down."""


class SchedulerPersistenceError(SchedulerError):
    """Scheduler storage operation failed."""


# =========================================================
# SCHEDULED JOB
# =========================================================

@dataclass
class ScheduledJob:
    job_id: str
    task_id: str
    run_at: str

    recurrence: str = "once"
    interval_seconds: Optional[float] = None

    platform: Optional[str] = None
    principal: str = "system"
    confirmed: bool = False

    status: str = "scheduled"

    max_retries: int = 0
    retry_count: int = 0
    retry_delay: float = 10.0

    created_at: str = ""
    last_run_at: Optional[str] = None
    completed_at: Optional[str] = None

    last_error: Optional[str] = None
    last_result_status: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(
                timezone.utc
            ).isoformat()


# =========================================================
# TASK SCHEDULER
# =========================================================

class TaskScheduler:
    """
    Persistent scheduler for Omi Vanguard AI.

    Uses TaskManager as the execution interface.
    """

    VALID_RECURRENCES = {
        "once",
        "daily",
        "weekly",
        "interval",
    }

    TERMINAL_STATES = {
        "completed",
        "failed",
        "cancelled",
    }

    def __init__(
        self,
        task_manager: Any,
        storage_path: str = "data/scheduled_jobs.json",
        poll_interval: float = 1.0,
    ) -> None:

        if task_manager is None:
            raise SchedulerError(
                "TaskManager is required."
            )

        self.task_manager = task_manager

        self.storage_path = Path(storage_path)

        self.poll_interval = max(
            0.1,
            float(poll_interval),
        )

        self._jobs: dict[str, ScheduledJob] = {}

        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)

        self._shutdown = False
        self._paused = False

        self._worker: Optional[threading.Thread] = None

        self._load_jobs()

    # =====================================================
    # INITIALIZATION
    # =====================================================

    def start(self) -> None:
        """Start the scheduler worker."""

        with self._condition:

            if self._shutdown:
                raise SchedulerShutdownError(
                    "Scheduler has been shut down."
                )

            if (
                self._worker is not None
                and self._worker.is_alive()
            ):
                return

            self._worker = threading.Thread(
                target=self._worker_loop,
                name="OmiVanguardScheduler",
                daemon=True,
            )

            self._worker.start()

            self._condition.notify_all()

    # =====================================================
    # DATETIME UTILITIES
    # =====================================================

    @staticmethod
    def _parse_datetime(value: str) -> datetime:

        try:
            result = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise SchedulerError(
                "Invalid ISO datetime."
            ) from exc

        if result.tzinfo is None:
            raise SchedulerError(
                "Datetime must include timezone information."
            )

        return result.astimezone(timezone.utc)

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    # =====================================================
    # SCHEDULING
    # =====================================================

    def schedule(
        self,
        task_id: str,
        delay_seconds: Optional[float] = None,
        run_at: Optional[str] = None,
        recurrence: str = "once",
        interval_seconds: Optional[float] = None,
        platform: Optional[str] = None,
        principal: str = "system",
        confirmed: bool = False,
        max_retries: int = 0,
        retry_delay: float = 10.0,
    ) -> str:
        """Schedule a registered task."""

        if self._shutdown:
            raise SchedulerShutdownError(
                "Scheduler is shut down."
            )

        if recurrence not in self.VALID_RECURRENCES:
            raise SchedulerError(
                f"Unsupported recurrence: {recurrence}"
            )

        if not isinstance(task_id, str) or not task_id.strip():
            raise SchedulerError(
                "Task ID cannot be empty."
            )

        if max_retries < 0 or retry_delay < 0:
            raise SchedulerError(
                "Retry settings cannot be negative."
            )

        self.task_manager.get_task(task_id)

        if delay_seconds is not None:

            if delay_seconds < 0:
                raise SchedulerError(
                    "Delay cannot be negative."
                )

            scheduled_time = (
                self._utc_now()
                + timedelta(seconds=delay_seconds)
            )

        elif run_at is not None:

            scheduled_time = self._parse_datetime(
                run_at
            )

        else:
            scheduled_time = self._utc_now()

        if recurrence == "interval":

            if (
                interval_seconds is None
                or interval_seconds <= 0
            ):
                raise SchedulerError(
                    "Interval must be greater than zero."
                )

        job_id = str(uuid.uuid4())

        job = ScheduledJob(
            job_id=job_id,
            task_id=task_id,
            run_at=scheduled_time.isoformat(),
            recurrence=recurrence,
            interval_seconds=interval_seconds,
            platform=platform,
            principal=principal,
            confirmed=confirmed,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        with self._condition:

            self._jobs[job_id] = job

            self._save_jobs()

            self._condition.notify_all()

        return job_id

    # =====================================================
    # WORKER
    # =====================================================

    def _worker_loop(self) -> None:
        """Background scheduler execution loop."""

        while True:

            with self._condition:

                if self._shutdown:
                    return

                if self._paused:
                    self._condition.wait(
                        timeout=self.poll_interval
                    )
                    continue

                now = self._utc_now()

                due_job = None
                next_wait = self.poll_interval

                for job in self._jobs.values():

                    if job.status != "scheduled":
                        continue

                    run_time = self._parse_datetime(
                        job.run_at
                    )

                    remaining = (
                        run_time - now
                    ).total_seconds()

                    if remaining <= 0:
                        due_job = job
                        job.status = "running"
                        job.last_run_at = now.isoformat()
                        self._save_jobs()
                        break

                    next_wait = min(
                        next_wait,
                        remaining,
                    )

                if due_job is None:

                    self._condition.wait(
                        timeout=max(0.1, next_wait)
                    )

                    continue

            self._execute_job(due_job)

    # =====================================================
    # EXECUTION
    # =====================================================

    def _execute_job(
        self,
        job: ScheduledJob,
    ) -> None:
        """Execute one scheduled task."""

        try:

            report = self.task_manager.execute_task(
                job.task_id,
                platform=job.platform,
                principal=job.principal,
                confirmed=job.confirmed,
            )

            result_status = getattr(
                report.status,
                "value",
                str(report.status),
            )

            job.last_result_status = result_status

            if result_status == "success":

                self._handle_success(job)

            elif result_status in (
                "cancelled",
                "rolled_back",
            ):

                self._handle_failure(
                    job,
                    f"Task ended with status: {result_status}",
                    retryable=False,
                )

            else:

                self._handle_failure(
                    job,
                    f"Task execution status: {result_status}",
                )

        except Exception as exc:

            self._handle_failure(
                job,
                str(exc),
            )

    # =====================================================
    # SUCCESS
    # =====================================================

    def _handle_success(
        self,
        job: ScheduledJob,
    ) -> None:

        with self._condition:

            job.retry_count = 0
            job.last_error = None

            job.completed_at = self._utc_now().isoformat()

            if job.recurrence == "once":

                job.status = "completed"

            else:

                self._schedule_next_occurrence(job)

                job.status = "scheduled"

            self._save_jobs()
            self._condition.notify_all()

    # =====================================================
    # FAILURE AND RETRY
    # =====================================================

    def _handle_failure(
        self,
        job: ScheduledJob,
        error: str,
        retryable: bool = True,
    ) -> None:

        with self._condition:

            job.last_error = error

            if (
                retryable
                and job.retry_count < job.max_retries
            ):

                job.retry_count += 1

                next_run = (
                    self._utc_now()
                    + timedelta(
                        seconds=job.retry_delay
                    )
                )

                job.run_at = next_run.isoformat()
                job.status = "scheduled"

            elif job.recurrence != "once":

                self._schedule_next_occurrence(job)
                job.status = "scheduled"

            else:

                job.status = "failed"
                job.completed_at = (
                    self._utc_now().isoformat()
                )

            self._save_jobs()
            self._condition.notify_all()

    # =====================================================
    # RECURRENCE
    # =====================================================

    def _schedule_next_occurrence(
        self,
        job: ScheduledJob,
    ) -> None:

        current = self._parse_datetime(
            job.run_at
        )

        if job.recurrence == "daily":

            next_time = current + timedelta(days=1)

        elif job.recurrence == "weekly":

            next_time = current + timedelta(days=7)

        elif job.recurrence == "interval":

            next_time = current + timedelta(
                seconds=job.interval_seconds
            )

        else:
            return

        job.run_at = next_time.isoformat()

        job.retry_count = 0

    # =====================================================
    # PAUSE AND RESUME
    # =====================================================

    def pause(self) -> None:
        """Pause future scheduled executions."""

        with self._condition:

            self._paused = True

            self._condition.notify_all()

    def resume(self) -> None:
        """Resume scheduled executions."""

        with self._condition:

            if self._shutdown:
                raise SchedulerShutdownError(
                    "Scheduler is shut down."
                )

            self._paused = False

            self._condition.notify_all()

    # =====================================================
    # CANCELLATION
    # =====================================================

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending scheduled job."""

        with self._condition:

            job = self._jobs.get(job_id)

            if job is None:
                raise ScheduledJobNotFoundError(
                    f"Job not found: {job_id}"
                )

            if job.status != "scheduled":
                return False

            job.status = "cancelled"

            job.completed_at = (
                self._utc_now().isoformat()
            )

            self._save_jobs()
            self._condition.notify_all()

            return True

    # =====================================================
    # RETRIEVAL
    # =====================================================

    def get_job(
        self,
        job_id: str,
    ) -> ScheduledJob:

        with self._lock:

            job = self._jobs.get(job_id)

            if job is None:
                raise ScheduledJobNotFoundError(
                    f"Job not found: {job_id}"
                )

            return job

    def list_jobs(
        self,
        status: Optional[str] = None,
    ) -> list[ScheduledJob]:

        with self._lock:

            jobs = list(self._jobs.values())

            if status is not None:

                jobs = [
                    job
                    for job in jobs
                    if job.status == status
                ]

            return jobs

    # =====================================================
    # PERSISTENCE
    # =====================================================

    def _save_jobs(self) -> None:
        """Save jobs atomically to JSON storage."""

        try:

            self.storage_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            data = [
                asdict(job)
                for job in self._jobs.values()
            ]

            temporary_path = self.storage_path.with_suffix(
                self.storage_path.suffix + ".tmp"
            )

            with open(
                temporary_path,
                "w",
                encoding="utf-8",
            ) as file:

                json.dump(
                    data,
                    file,
                    indent=4,
                    ensure_ascii=False,
                )

                file.flush()
                os.fsync(file.fileno())

            os.replace(
                temporary_path,
                self.storage_path,
            )

        except Exception as exc:

            raise SchedulerPersistenceError(
                f"Could not save scheduled jobs: {exc}"
            ) from exc

    def _load_jobs(self) -> None:
        """Restore jobs from persistent JSON storage."""

        if not self.storage_path.exists():
            return

        try:

            with open(
                self.storage_path,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

            if not isinstance(data, list):
                raise ValueError(
                    "Invalid scheduler storage format."
                )

            for item in data:

                job = ScheduledJob(**item)

                if job.status == "running":

                    job.status = "scheduled"
                    job.run_at = (
                        self._utc_now().isoformat()
                    )

                if job.status == "scheduled":

                    self._jobs[job.job_id] = job

                else:

                    self._jobs[job.job_id] = job

        except Exception as exc:

            raise SchedulerPersistenceError(
                f"Could not load scheduled jobs: {exc}"
            ) from exc

    # =====================================================
    # STATUS
    # =====================================================

    def get_status(self) -> dict[str, Any]:

        with self._lock:

            counts = {
                "scheduled": 0,
                "running": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
            }

            for job in self._jobs.values():

                counts[job.status] = (
                    counts.get(job.status, 0) + 1
                )

            return {
                "scheduler": type(self).__name__,
                "shutdown": self._shutdown,
                "paused": self._paused,
                "worker_running": (
                    self._worker is not None
                    and self._worker.is_alive()
                ),
                "total_jobs": len(self._jobs),
                "job_statuses": counts,
                "storage_path": str(
                    self.storage_path
                ),
            }

    # =====================================================
    # SHUTDOWN
    # =====================================================

    def shutdown(
        self,
        cancel_pending: bool = False,
        wait: bool = True,
    ) -> None:
        """Stop the scheduler worker."""

        with self._condition:

            self._shutdown = True

            if cancel_pending:

                for job in self._jobs.values():

                    if job.status == "scheduled":
                        job.status = "cancelled"

            self._save_jobs()

            self._condition.notify_all()

        if (
            wait
            and self._worker is not None
            and self._worker is not threading.current_thread()
        ):

            self._worker.join(timeout=10)
