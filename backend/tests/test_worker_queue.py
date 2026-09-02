from datetime import datetime, timedelta, timezone

from app.workers.queue import InMemoryJobQueue, JobStatus, ProcessingJob


def test_queue_claims_next_ready_job_and_tracks_attempts() -> None:
    queue = InMemoryJobQueue()
    first = queue.enqueue("lead-1", "enrich", {"source": "manual"})
    second = queue.enqueue("lead-2", "research", {"source": "manual"})

    claimed = queue.claim_next("worker-a")

    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == JobStatus.RUNNING
    assert claimed.attempts == 1
    assert claimed.claimed_by == "worker-a"
    assert queue.get(first.id).status == JobStatus.RUNNING
    assert queue.get(second.id).status == JobStatus.QUEUED


def test_failed_job_is_requeued_until_max_attempts() -> None:
    queue = InMemoryJobQueue()
    job = queue.enqueue("lead-9", "enrich", {"source": "manual"}, max_attempts=2)

    claimed = queue.claim_next("worker-a")
    assert claimed is not None and claimed.id == job.id

    queue.fail_job(job.id, RuntimeError("temporary network issue"))
    assert queue.get(job.id).status == JobStatus.QUEUED
    assert queue.get(job.id).attempts == 1

    queue.get(job.id).run_after = datetime.now(timezone.utc)
    claimed_again = queue.claim_next("worker-b")
    assert claimed_again is not None and claimed_again.id == job.id

    queue.fail_job(job.id, RuntimeError("still failing"))
    assert queue.get(job.id).status == JobStatus.FAILED
    assert queue.get(job.id).attempts == 2


def test_completed_job_clears_error_and_sets_result() -> None:
    queue = InMemoryJobQueue()
    job = queue.enqueue("lead-4", "score", {"mode": "async"})
    queue.claim_next("worker-z")

    queue.complete_job(job.id, {"score": 92, "disposition": "Strong Fit"})

    stored = queue.get(job.id)
    assert stored.status == JobStatus.COMPLETED
    assert stored.result == {"score": 92, "disposition": "Strong Fit"}
    assert stored.error_message is None
    assert stored.claimed_by is None


def test_ready_jobs_ignore_future_run_after_times() -> None:
    queue = InMemoryJobQueue()
    queue.enqueue("lead-5", "research", {"source": "manual"}, run_after=datetime.now(timezone.utc) + timedelta(minutes=5))
    queued = queue.claim_next("worker-a")

    assert queued is None
