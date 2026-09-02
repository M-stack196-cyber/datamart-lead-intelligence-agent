from unittest.mock import Mock

from app.intent import CaptureResult, IntentScore
from app.services.live_capture import CaptureScheduler
from app.workers.queue import InMemoryJobQueue


def test_capture_scheduler_enqueues_only_quality_matches_for_live_processing() -> None:
    queue = InMemoryJobQueue()
    agent = Mock()
    agent.capture.side_effect = [
        CaptureResult(
            matched=True,
            normalized_fields={
                "person_name": "Aisha Rafiq",
                "company_name": "Datamart",
                "title": "Founder",
                "linkedin_url": "https://linkedin.com/in/aisha",
            },
            evidence=[{"title": "Hiring", "source_url": "https://example.com/hiring", "excerpt": "Expanding product team"}],
            evidence_urls=["https://example.com/hiring"],
            intent=IntentScore(score=82, level="high", reasons=["Evidence available"], evidence_urls=["https://example.com/hiring"]),
        ),
        CaptureResult(
            matched=False,
            normalized_fields={"company_name": "Unknown"},
            evidence=[],
            evidence_urls=[],
            intent=IntentScore(score=10, level="low", reasons=["No evidence"], evidence_urls=[]),
        ),
    ]

    scheduler = CaptureScheduler(agent, queue)
    jobs = scheduler.run_cycle([
        {"id": "lead-1", "company_name": "Datamart", "linkedin_url": "https://linkedin.com/in/aisha"},
        {"id": "lead-2", "company_name": "Unknown"},
    ])

    assert len(jobs) == 1
    assert jobs[0].lead_id == "lead-1"
    assert jobs[0].job_type == "enrich"
    assert jobs[0].payload["source"] == "live_capture"
    assert jobs[0].payload["intent_score"] == 82
