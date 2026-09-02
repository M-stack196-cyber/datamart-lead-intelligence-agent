from app.workers.queue import InMemoryJobQueue, JobStatus
from app.workers.runner import process_next_job


class FakeProvider:
    def enrich(self, lead):
        return type(
            "Result",
            (),
            {
                "matched": True,
                "fields": {"person_name": "Aisha Rafiq"},
                "evidence": [
                    {
                        "title": "Hiring expansion",
                        "source_url": "https://example.com/hiring",
                        "evidence_type": "job_post",
                        "publisher": "Example",
                        "excerpt": "Hiring for GTM roles",
                        "supports_fields": ["person_name"],
                        "metadata": {"confidence": 0.9},
                    }
                ],
                "prospect_id": "prospect-123",
                "raw_result": {"provider": "fake"},
            },
        )()


def test_process_next_job_updates_queue_result_for_enrichment() -> None:
    queue = InMemoryJobQueue()
    job = queue.enqueue("lead-42", "enrich", {"source": "live_capture", "lead": {"id": "lead-42", "company_name": "Datamart"}})

    processed = process_next_job(queue, FakeProvider(), worker_name="worker-a")

    assert processed is True
    stored = queue.get(job.id)
    assert stored.status == JobStatus.COMPLETED
    assert stored.result["matched"] is True
    assert stored.result["updated_fields"] == ["person_name"]
    assert stored.result["evidence_count"] == 1
