"""Persistent, single-worker task scheduler."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


class SchedulerError(RuntimeError):
    """Scheduler operation failed."""


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


class TaskScheduler:
    """Schedules TaskManager.execute_task calls. Recurrence uses UTC."""

    RECURRENCES = {"once", "daily", "weekly", "interval"}
    STATUSES = {"scheduled", "running", "completed", "failed", "cancelled"}

    def __init__(
        self,
        task_manager: Any,
        storage_path: str = "data/scheduled_jobs.json",
        poll_interval: float = 1.0,
    ) -> None:
        if not callable(getattr(task_manager, "execute_task", None)):
            raise TypeError("task_manager must provide execute_task()")

        if (
            isinstance(poll_interval, bool)
            or not isinstance(poll_interval, (int, float))
            or poll_interval <= 0
        ):
            raise ValueError("poll_interval must be positive")

        self.task_manager = task_manager
        self.storage_path = Path(storage_path)
        self.poll_interval = float(poll_interval)

        self._jobs: Dict[str, ScheduledJob] = {}
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._shutdown = False
        self._paused = False

        self._load()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse(value: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("run_at must be an ISO-8601 datetime")

        result = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("run_at must include a timezone")

        return result.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _copy(job: ScheduledJob) -> ScheduledJob:
        return ScheduledJob(**asdict(job))

    def _load(self) -> None:
        if not self.storage_path.exists():
            return

        try:
            rows = json.loads(
                self.storage_path.read_text(encoding="utf-8")
            )

            if not isinstance(rows, list):
                raise ValueError("storage root must be a list")

            allowed = set(ScheduledJob.__dataclass_fields__)
            loaded = {}

            for row in rows:
                if not isinstance(row, dict) or set(row) - allowed:
                    raise ValueError("invalid job record")

                job = ScheduledJob(**row)

                if not job.job_id or job.job_id in loaded:
                    raise ValueError("missing or duplicate job ID")

                if job.status == "running":
                    job.status = "scheduled"
                    job.run_at = self._iso(self._now())

                if job.status not in self.STATUSES:
                    raise ValueError("invalid job status")

                self._parse(job.run_at)
                loaded[job.job_id] = job

            self._jobs = loaded

        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise SchedulerError(
                f"Could not load scheduler storage: {exc}"
            ) from exc

    def _save(self) -> None:
        self.storage_path.parent.mkdir(
            parents=True, exist_ok=True
        )

        fd, temp_path = tempfile.mkstemp(
            dir=str(self.storage_path.parent),
            prefix=self.storage_path.name,
            suffix=".tmp",
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    [asdict(job) for job in self._jobs.values()],
                    stream,
                    ensure_ascii=False,
                    indent=2,
                )
                stream.flush()
                os.fsync(stream.fileno())

            os.replace(temp_path, self.storage_path)

        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def _ensure_open(self) -> None:
        if self._shutdown:
            raise SchedulerError("scheduler has been shut down")

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
    ) -> ScheduledJob:

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be non-empty")

        if recurrence not in self.RECURRENCES:
            raise ValueError(
                f"recurrence must be one of {sorted(self.RECURRENCES)}"
            )

        if delay_seconds is not None and run_at is not None:
            raise ValueError(
                "provide delay_seconds or run_at, not both"
            )

        if delay_seconds is not None:
            if (
                isinstance(delay_seconds, bool)
                or not isinstance(delay_seconds, (int, float))
                or delay_seconds < 0
            ):
                raise ValueError("delay_seconds must be non-negative")

            when = self._now() + timedelta(
                seconds=float(delay_seconds)
            )
        else:
            when = (
                self._parse(run_at)
                if run_at is not None
                else self._now()
            )

        if recurrence == "interval":
            if (
                isinstance(interval_seconds, bool)
                or not isinstance(interval_seconds, (int, float))
                or interval_seconds <= 0
            ):
                raise ValueError(
                    "interval_seconds must be positive for interval recurrence"
                )
        elif interval_seconds is not None:
            raise ValueError(
                "interval_seconds only applies to interval recurrence"
            )

        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")

        if (
            isinstance(retry_delay, bool)
            or not isinstance(retry_delay, (int, float))
            or retry_delay < 0
        ):
            raise ValueError("retry_delay must be non-negative")

        if not isinstance(principal, str) or not principal.strip():
            raise ValueError("principal must be non-empty")

        if platform is not None and (
            not isinstance(platform, str) or not platform.strip()
        ):
            raise ValueError("platform must be non-empty or None")

        if not isinstance(confirmed, bool):
            raise TypeError("confirmed must be bool")

        getter = getattr(self.task_manager, "get_task", None)

        if callable(getter) and getter(task_id) is None:
            raise SchedulerError(
                f"Task {task_id!r} is not registered"
            )

        now = self._iso(self._now())

        job = ScheduledJob(
            job_id=str(uuid4()),
            task_id=task_id,
            run_at=self._iso(when),
            recurrence=recurrence,
            interval_seconds=(
                float(interval_seconds)
                if interval_seconds is not None
                else None
            ),
            platform=platform,
            principal=principal,
            confirmed=confirmed,
            status="scheduled",
            max_retries=max_retries,
            retry_count=0,
            retry_delay=float(retry_delay),
            created_at=now,
        )

        with self._lock:
            self._ensure_open()
            self._jobs[job.job_id] = job

            try:
                self._save()
            except Exception:
                del self._jobs[job.job_id]
                raise

        self._wake.set()
        return self._copy(job)

    def get_job(self, job_id: str) -> ScheduledJob:
        with self._lock:
            if job_id not in self._jobs:
                raise SchedulerError(f"Unknown job: {job_id}")

            return self._copy(self._jobs[job_id])

    def list_jobs(
        self, status: Optional[str] = None
    ) -> List[ScheduledJob]:

        with self._lock:
            jobs = list(self._jobs.values())

            if status is not None:
                jobs = [job for job in jobs if job.status == status]

            return [self._copy(job) for job in jobs]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)

            if job is None:
                raise SchedulerError(f"Unknown job: {job_id}")

            if job.status != "scheduled":
                return False

            job.status = "cancelled"
            self._save()

        self._wake.set()
        return True

    def pause(self) -> None:
        with self._lock:
            self._ensure_open()
            self._paused = True

        self._wake.set()

    def resume(self) -> None:
        with self._lock:
            self._ensure_open()
            self._paused = False

        self._wake.set()

    def start(self) -> None:
        with self._lock:
            self._ensure_open()

            if self._thread and self._thread.is_alive():
                return

            self._thread = threading.Thread(
                target=self._worker,
                name="OmiTaskScheduler",
                daemon=True,
            )
            self._thread.start()

    def _worker(self) -> None:
        while True:
            with self._lock:
                if self._shutdown:
                    return

                due_job = None

                if not self._paused:
                    now = self._now()

                    due = [
                        job
                        for job in self._jobs.values()
                        if job.status == "scheduled"
                        and self._parse(job.run_at) <= now
                    ]

                    if due:
                        due_job = min(
                            due,
                            key=lambda job: self._parse(job.run_at),
                        )

                        due_job.status = "running"
                        due_job.last_run_at = self._iso(now)

                        try:
                            self._save()
                        except Exception as exc:
                            due_job.status = "scheduled"
                            due_job.last_error = (
                                f"Storage error: {exc}"
                            )
                            due_job.run_at = self._iso(
                                now + timedelta(
                                    seconds=self.poll_interval
                                )
                            )
                            due_job = None

            if due_job:
                self._run_job(due_job.job_id)
            else:
                self._wake.wait(self.poll_interval)
                self._wake.clear()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)

            if job is None or job.status != "running":
                return

            snapshot = self._copy(job)

        try:
            task_plan = self.task_manager.get_task(
                snapshot.task_id
            )

            if task_plan is None:
                raise SchedulerError(
                    f"Task {snapshot.task_id!r} is no longer registered"
                )

            report = self.task_manager.execute_task(
                task_plan,
                platform=snapshot.platform,
                principal=snapshot.principal,
                confirmed=snapshot.confirmed,
            )

            status = getattr(report, "status", None)
            status = getattr(status, "value", status)

            success = str(status).lower() in {
                "success",
                "completed",
            }

            error = (
                None
                if success
                else f"Task returned status: {status}"
            )

        except Exception as exc:
            success = False
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"

        with self._lock:
            job = self._jobs.get(job_id)

            if job is None:
                return

            job.last_result_status = str(status)

            if success:
                job.last_error = None
                job.retry_count = 0

                if job.recurrence == "once":
                    job.status = "completed"
                    job.completed_at = self._iso(self._now())
                else:
                    job.status = "scheduled"
                    job.run_at = self._next_run(job)

            elif job.retry_count < job.max_retries:
                job.retry_count += 1
                job.last_error = error
                job.status = "scheduled"
                job.run_at = self._iso(
                    self._now()
                    + timedelta(seconds=job.retry_delay)
                )

            elif job.recurrence == "once":
                job.last_error = error
                job.status = "failed"
                job.completed_at = self._iso(self._now())

            else:
                job.last_error = error
                job.retry_count = 0
                job.status = "scheduled"
                job.run_at = self._next_run(job)

            self._save()

    def _next_run(self, job: ScheduledJob) -> str:
        previous = self._parse(job.run_at)

        delta = {
            "daily": timedelta(days=1),
            "weekly": timedelta(days=7),
            "interval": timedelta(
                seconds=float(job.interval_seconds)
            ),
        }.get(job.recurrence)

        if delta is None:
            raise SchedulerError("one-time job has no next run")

        next_time = previous + delta
        now = self._now()

        while next_time <= now:
            next_time += delta

        return self._iso(next_time)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            counts = {
                status: 0
                for status in self.STATUSES
            }

            for job in self._jobs.values():
                counts[job.status] = (
                    counts.get(job.status, 0) + 1
                )

            return {
                "running": bool(
                    self._thread and self._thread.is_alive()
                ),
                "paused": self._paused,
                "shutdown": self._shutdown,
                "job_count": len(self._jobs),
                "jobs_by_status": counts,
            }

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            self._shutdown = True
            thread = self._thread

        self._wake.set()

        if (
            wait
            and thread is not None
            and thread is not threading.current_thread()
        ):
            thread.join()
