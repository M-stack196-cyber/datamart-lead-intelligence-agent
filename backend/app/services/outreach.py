from __future__ import annotations

from typing import Any


class OutreachDraftEngine:
    """Draft a reviewable outbound message using known lead facts and evidence URLs."""

    @staticmethod
    def draft(lead: dict[str, Any], evidence: list[dict[str, Any]], *, channel: str = "email") -> dict[str, Any]:
        person = str(lead.get("person_name") or "there").strip()
        company = str(lead.get("company_name") or "your company").strip()
        title = str(lead.get("title") or "team leader").strip()

        subject = f"{company} could be a fit for Datamart"
        lines = [
            f"Hi {person},",
            "",
            f"I noticed your role as {title} at {company}, and I think there may be a strong fit with Datamart.",
            "",
            "Relevant evidence:",
        ]

        for item in evidence[:3]:
            url = str(item.get("source_url") or "").strip()
            title_text = str(item.get("title") or "Evidence").strip()
            if url:
                lines.append(f"- {title_text}: {url}")

        lines.extend([
            "",
            "Would you be open to a brief conversation to explore whether this is relevant for your roadmap?",
            "",
            "Best,",
            "Datamart Lead Intelligence Agent",
        ])

        return {
            "channel": channel,
            "subject": subject,
            "body": "\n".join(lines),
        }
