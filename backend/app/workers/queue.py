from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock
from typing import Any
import uuid


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ProcessingJob:
    id: str
    lead_id: str
    job_type: str
    payload: dict[str, Any]
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    run_after: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    claimed_by: str | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None
    completed_at: datetime | None = None


class InMemoryJobQueue:
    """In-memory durable queue contract used to test the job lifecycle before DB-backed processing is added."""

    def __init__(self) -> None:
        self._jobs: dict[str, ProcessingJob] = {}
        self._lock = Lock()

    def enqueue(
        self,
        lead_id: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
        run_after: datetime | None = None,
    ) -> ProcessingJob:
        job = ProcessingJob(
            id=f"job-{uuid.uuid4().hex[:12]}",
            lead_id=lead_id,
            job_type=job_type,
            payload=payload,
            max_attempts=max_attempts,
            run_after=run_after or datetime.now(timezone.utc),
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> ProcessingJob:
        with self._lock:
            return self._jobs[job_id]

    def claim_next(self, worker_name: str) -> ProcessingJob | None:
        with self._lock:
            now = datetime.now(timezone.utc)
            candidates = [
                job for job in self._jobs.values()
                if job.status == JobStatus.QUEUED and job.run_after <= now and job.attempts < job.max_attempts
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda job: (job.run_after, job.id))
            job = candidates[0]
            job.status = JobStatus.RUNNING
            job.attempts += 1
            job.claimed_by = worker_name
            job.error_message = None
            return job

    def fail_job(self, job_id: str, error: Exception) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.error_message = str(error)[:1000]
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.FAILED
                job.claimed_by = None
                job.run_after = datetime.now(timezone.utc)
            else:
                job.status = JobStatus.QUEUED
                job.claimed_by = None
                job.run_after = datetime.now(timezone.utc) + timedelta(seconds=30)

    def complete_job(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.COMPLETED
            job.result = result
            job.error_message = None
            job.claimed_by = None
            job.completed_at = datetime.now(timezone.utc)

    def list_ready(self) -> list[ProcessingJob]:
        now = datetime.now(timezone.utc)
        with self._lock:
            return [
                job for job in self._jobs.values()
                if job.status == JobStatus.QUEUED and job.run_after <= now
            ]
