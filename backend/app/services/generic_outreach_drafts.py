from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class DraftPreview:
    lead_id: str
    channel: str
    subject: str | None
    body: str


@dataclass(frozen=True)
class GenericDraftGenerationResult:
    source: str
    requested_limit: int
    eligible_leads: int
    skipped_existing: int
    email_drafts_created: int
    linkedin_drafts_created: int
    errors: list[str]
    previews: list[DraftPreview]


def generate_primary_drafts_for_review_leads(
    client: Any,
    source: str = "apollo_csv",
    limit: int = 25,
    create_linkedin: bool = True,
    create_email: bool = True,
    *,
    dry_run: bool = False,
) -> GenericDraftGenerationResult:
    if limit < 1:
        raise ValueError("Draft generation limit must be at least one")

    leads = _review_leads(client, source, limit)
    errors: list[str] = []
    previews: list[DraftPreview] = []
    skipped_existing = 0
    email_created = 0
    linkedin_created = 0

    for lead in leads:
        lead_id = str(lead.get("id") or "")
        if not lead_id:
            errors.append("A review lead was missing an id")
            continue

        existing_channels = _existing_primary_channels(client, lead_id)
        score = _latest_score(client, lead_id)
        channels = []
        if create_email:
            channels.append("email")
        if create_linkedin:
            channels.append("linkedin")

        for channel in channels:
            if channel in existing_channels:
                skipped_existing += 1
                continue

            draft = _draft_for_channel(lead, score, channel)
            preview = DraftPreview(
                lead_id=lead_id,
                channel=channel,
                subject=draft["subject"],
                body=draft["body"],
            )
            previews.append(preview)

            if not dry_run:
                try:
                    _insert_draft(client, lead_id, draft)
                except Exception as exc:
                    errors.append(
                        f"Lead {lead_id} {channel} draft was not created: {type(exc).__name__}"
                    )
                    continue

            if channel == "email":
                email_created += 1
            else:
                linkedin_created += 1

    return GenericDraftGenerationResult(
        source=source,
        requested_limit=limit,
        eligible_leads=len(leads),
        skipped_existing=skipped_existing,
        email_drafts_created=email_created,
        linkedin_drafts_created=linkedin_created,
        errors=errors,
        previews=previews[:3],
    )


def _review_leads(client: Any, source: str, limit: int) -> list[dict[str, Any]]:
    rows = (
        client.table("leads")
        .select(
            "id,person_name,title,company_name,company_url,linkedin_url,email,"
            "country,industry,lead_source,status,raw_source_data,source_captured_at"
        )
        .eq("lead_source", source)
        .eq("status", "review")
        .order("source_captured_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return [row for row in rows if isinstance(row, dict)]


def _latest_score(client: Any, lead_id: str) -> dict[str, Any]:
    rows = (
        client.table("lead_scores")
        .select(
            "score,disposition,tier,persona,hard_stops,review_reasons,"
            "evaluations,scored_at"
        )
        .eq("lead_id", lead_id)
        .order("scored_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows and isinstance(rows[0], dict) else {}


def _existing_primary_channels(client: Any, lead_id: str) -> set[str]:
    rows = (
        client.table("outreach_drafts")
        .select("id,channel,sequence_step,status")
        .eq("lead_id", lead_id)
        .eq("sequence_step", 1)
        .execute()
        .data
        or []
    )
    return {
        str(row.get("channel"))
        for row in rows
        if isinstance(row, dict) and row.get("channel") in {"email", "linkedin"}
    }


def _insert_draft(client: Any, lead_id: str, draft: dict[str, Any]) -> None:
    (
        client.table("outreach_drafts")
        .insert(
            {
                "lead_id": lead_id,
                "sequence_step": 1,
                "channel": draft["channel"],
                "subject": draft["subject"],
                "body": draft["body"],
                "status": "draft",
                "evidence_ids": [],
                "created_by": None,
                "reviewed_by": None,
                "reviewed_at": None,
                "review_notes": None,
            }
        )
        .execute()
    )


def _draft_for_channel(
    lead: dict[str, Any],
    score: dict[str, Any],
    channel: str,
) -> dict[str, Any]:
    if channel == "email":
        return {
            "channel": "email",
            "subject": _email_subject(lead),
            "body": _email_body(lead, score),
        }
    if channel == "linkedin":
        return {
            "channel": "linkedin",
            "subject": None,
            "body": _linkedin_body(lead, score),
        }
    raise ValueError("Outreach channel must be email or linkedin")


def _email_subject(lead: dict[str, Any]) -> str:
    company = _text(lead.get("company_name"), "your team")
    return f"Quick question about {company}"


def _email_body(lead: dict[str, Any], score: dict[str, Any]) -> str:
    person = _first_name(lead.get("person_name")) or "there"
    company = _text(lead.get("company_name"), "your company")
    title = _text(lead.get("title"), "your role")
    domain = _domain(lead.get("company_url"))
    context = _context_line(lead, score)

    lines = [
        f"Hi {person},",
        "",
        f"I’m reaching out because {company}"
        + (f" ({domain})" if domain else "")
        + f" looks relevant to the kind of work Datamart supports, and I saw your role as {title}.",
        context,
        "",
        "Datamart helps teams with AI agents and CRM/workflow automation when they need practical engineering capacity.",
        "",
        "Would it be worth a quick 10-minute conversation?",
        "",
        "Best,",
        "Datamart",
    ]
    return "\n".join(lines)


def _linkedin_body(lead: dict[str, Any], score: dict[str, Any]) -> str:
    person = _first_name(lead.get("person_name")) or "there"
    company = _text(lead.get("company_name"), "your team")
    focus = _short_focus(lead, score)
    return (
        f"Hi {person}, noticed {company} looks relevant to {focus}. "
        "Datamart works on AI agents and workflow/software automation. "
        "Would it be okay to send one brief idea?"
    )


def _context_line(lead: dict[str, Any], score: dict[str, Any]) -> str:
    reasons = _review_reasons(score)
    industry = _text(lead.get("industry"), "")
    if reasons:
        return f"The ICP review flagged: {reasons[0]}."
    if industry:
        return f"The ICP review marked {industry} as a possible fit for software and automation support."
    return "The ICP review marked this as worth a human look before any outreach."


def _short_focus(lead: dict[str, Any], score: dict[str, Any]) -> str:
    reasons = " ".join(_review_reasons(score)).casefold()
    industry = str(lead.get("industry") or "").casefold()
    text = f"{reasons} {industry}"
    if "health" in text:
        return "healthtech workflow automation"
    if "fintech" in text or "financial" in text:
        return "fintech workflow automation"
    if "ai" in text:
        return "AI-enabled operations"
    if "saas" in text or "software" in text:
        return "SaaS/backend engineering"
    if "crm" in text:
        return "CRM and workflow automation"
    return "software and workflow automation"


def _review_reasons(score: dict[str, Any]) -> list[str]:
    reasons = score.get("review_reasons")
    if not isinstance(reasons, list):
        return []
    return [str(reason).strip() for reason in reasons if str(reason).strip()]


def _domain(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text if "://" in text else "https://" + text)
    host = (parsed.hostname or "").removeprefix("www.")
    return host or None


def _first_name(value: Any) -> str | None:
    text = str(value or "").strip()
    return text.split()[0] if text else None


def _text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback
