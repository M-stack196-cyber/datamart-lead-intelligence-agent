from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


UNSUPPORTED_ACTIVITY_PATTERNS = (
    r"\byou\s+(?:posted|commented|announced|shared|said)\b",
    r"\byour\s+(?:post|comment)\b",
    r"\bi\s+(?:saw|noticed)\s+your?\b",
)


def validate_outreach_for_approval(
    body: str,
    evidence: list[dict[str, Any]],
    lead: dict[str, Any] | None = None,
) -> None:
    if not body.strip():
        raise ValueError("Outreach body is required")
    if len(body) > 4000:
        raise ValueError("Outreach body exceeds 4000 characters")
    if not evidence:
        raise ValueError("Stored evidence is required before outreach approval")
    for pattern in UNSUPPORTED_ACTIVITY_PATTERNS:
        if re.search(pattern, body, flags=re.IGNORECASE):
            raise ValueError("Unsupported personal activity claim in outreach draft")
    grounding_text = " ".join(
        str(value)
        for item in evidence
        for value in (item.get("title"), item.get("excerpt"), item.get("publisher"))
        if value
    )
    if lead:
        grounding_text += " " + " ".join(
            str(lead.get(key) or "")
            for key in ("person_name", "company_name", "title", "country", "industry")
        )
    grounding_text = grounding_text.casefold()
    factual_tokens = re.findall(
        r"\$\s?\d[\d,.]*[kmb]?|\b\d+(?:\.\d+)?%|\b(?:raised|funded|funding|hiring|expanding|launched|revenue|employees)\b",
        body,
        flags=re.IGNORECASE,
    )
    if any(token.casefold().replace(" ", "") not in grounding_text.replace(" ", "") for token in factual_tokens):
        raise ValueError("Outreach draft contains a factual claim not found in stored evidence")


class OutreachDraftEngine:
    """Draft a reviewable outbound message using known lead facts and evidence URLs."""

    @staticmethod
    def draft(
        lead: dict[str, Any],
        evidence: list[dict[str, Any]],
        *,
        channel: str = "email",
        persona: str | None = None,
    ) -> dict[str, Any]:
        if channel not in {"email", "linkedin"}:
            raise ValueError("Outreach channel must be email or linkedin")
        stored_evidence: list[dict[str, Any]] = []
        for item in evidence:
            url = item.get("source_url") if isinstance(item, dict) else None
            if not isinstance(url, str):
                continue
            parsed = urlparse(url.strip())
            if parsed.scheme in {"http", "https"} and parsed.netloc and item.get("id"):
                stored_evidence.append(item)
        if not stored_evidence:
            raise ValueError("Stored evidence is required before drafting outreach")

        person = str(lead.get("person_name") or "there").strip()
        company = str(lead.get("company_name") or "your company").strip()
        title = str(lead.get("title") or "").strip()

        subject = f"{company}: a question" if channel == "email" else None
        lines = [
            f"Hi {person},",
            "",
        ]
        if title:
            lines.append(f"I’m reaching out regarding your role as {title} at {company}.")
        else:
            lines.append(f"I’m reaching out regarding {company}.")
        if persona:
            lines.append(f"Your profile matched our {persona} review context.")
        lines.extend(["", "A public source in our stored research:"])

        for item in stored_evidence[:2]:
            url = str(item.get("source_url") or "").strip()
            title_text = str(item.get("title") or "Source").strip()
            publisher = str(item.get("publisher") or "public source").strip()
            lines.append(f"- {title_text} ({publisher}): {url}")

        lines.extend([
            "",
            "Would you be open to a brief conversation about whether Datamart could support your current software priorities?",
            "",
            "Best,",
            "Datamart",
        ])

        body = "\n".join(lines)
        validate_outreach_for_approval(body, stored_evidence, lead)

        return {
            "channel": channel,
            "subject": subject,
            "body": body,
            "evidence_ids": [str(item["id"]) for item in stored_evidence[:2]],
        }
