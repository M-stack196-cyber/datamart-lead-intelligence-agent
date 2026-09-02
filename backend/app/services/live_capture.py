from __future__ import annotations

from typing import Any

from app.intent import CaptureResult
from app.workers.queue import InMemoryJobQueue, ProcessingJob


class CaptureScheduler:
    """Convert live-captured leads into queueable enrichment jobs when they have sufficient quality."""

    def __init__(self, agent: Any, queue: InMemoryJobQueue | None = None) -> None:
        self.agent = agent
        self.queue = queue or InMemoryJobQueue()

    def run_cycle(self, leads: list[dict[str, Any]]) -> list[ProcessingJob]:
        created: list[ProcessingJob] = []
        for lead in leads:
            result = self.agent.capture(lead)
            if not isinstance(result, CaptureResult):
                continue
            if not result.matched or result.intent.score < 60:
                continue

            job = self.queue.enqueue(
                str(lead.get("id") or lead.get("lead_id") or len(created)),
                "enrich",
                {
                    "source": "live_capture",
                    "intent_score": result.intent.score,
                    "intent_level": result.intent.level,
                    "normalized_fields": result.normalized_fields,
                    "evidence_urls": result.evidence_urls,
                },
            )
            created.append(job)
        return created
