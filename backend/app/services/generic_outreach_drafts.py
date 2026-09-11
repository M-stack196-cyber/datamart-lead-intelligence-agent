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


@dataclass(frozen=True)
class GenericFollowupDraftGenerationResult:
    source: str
    requested_limit: int
    followup_step: int
    eligible_leads: int
    skipped_missing_previous: int
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

        existing_drafts = _drafts_for_lead(client, lead_id)
        existing_channels = _existing_primary_channels(existing_drafts)
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
                    _insert_draft(client, lead_id, draft, sequence_step=1)
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


def generate_followup_drafts_for_review_leads(
    client: Any,
    source: str = "apollo_csv",
    limit: int = 25,
    followup_step: int = 2,
    create_email: bool = True,
    create_linkedin: bool = True,
    dry_run: bool = False,
) -> GenericFollowupDraftGenerationResult:
    if followup_step not in {2, 3, 4}:
        raise ValueError("Follow-up step must be 2, 3, or 4")
    if limit < 1:
        raise ValueError("Draft generation limit must be at least one")

    leads = _review_leads(client, source, limit)
    errors: list[str] = []
    previews: list[DraftPreview] = []
    skipped_missing_previous = 0
    skipped_existing = 0
    email_created = 0
    linkedin_created = 0

    for lead in leads:
        lead_id = str(lead.get("id") or "")
        if not lead_id:
            errors.append("A review lead was missing an id")
            continue

        existing_drafts = _drafts_for_lead(client, lead_id)
        score = _latest_score(client, lead_id)
        channels = []
        if create_email:
            channels.append("email")
        if create_linkedin:
            channels.append("linkedin")

        for channel in channels:
            if _has_existing_step(existing_drafts, channel, followup_step):
                skipped_existing += 1
                continue
            if not _has_valid_previous_step(existing_drafts, channel, followup_step - 1):
                skipped_missing_previous += 1
                continue

            draft = _followup_draft_for_channel(lead, score, channel, followup_step)
            preview = DraftPreview(
                lead_id=lead_id,
                channel=channel,
                subject=draft["subject"],
                body=draft["body"],
            )
            previews.append(preview)

            if not dry_run:
                try:
                    _insert_draft(client, lead_id, draft, sequence_step=followup_step)
                except Exception as exc:
                    errors.append(
                        f"Lead {lead_id} {channel} follow-up step {followup_step} was not created: {type(exc).__name__}"
                    )
                    continue

            if channel == "email":
                email_created += 1
            else:
                linkedin_created += 1

    return GenericFollowupDraftGenerationResult(
        source=source,
        requested_limit=limit,
        followup_step=followup_step,
        eligible_leads=len(leads),
        skipped_missing_previous=skipped_missing_previous,
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


def _drafts_for_lead(client: Any, lead_id: str) -> list[dict[str, Any]]:
    rows = (
        client.table("outreach_drafts")
        .select("id,channel,sequence_step,status")
        .eq("lead_id", lead_id)
        .execute()
        .data
        or []
    )
    return [row for row in rows if isinstance(row, dict)]


def _existing_primary_channels(existing_drafts: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("channel"))
        for row in existing_drafts
        if _same_step(row, 1) and row.get("channel") in {"email", "linkedin"}
    }


def _has_existing_step(
    existing_drafts: list[dict[str, Any]],
    channel: str,
    sequence_step: int,
) -> bool:
    return any(_same_channel_step(row, channel, sequence_step) for row in existing_drafts)


def _has_valid_previous_step(
    existing_drafts: list[dict[str, Any]],
    channel: str,
    sequence_step: int,
) -> bool:
    return any(
        _same_channel_step(row, channel, sequence_step)
        and str(row.get("status") or "").casefold() not in {"rejected", "cancelled"}
        for row in existing_drafts
    )


def _same_channel_step(row: dict[str, Any], channel: str, sequence_step: int) -> bool:
    return str(row.get("channel") or "") == channel and _same_step(row, sequence_step)


def _same_step(row: dict[str, Any], sequence_step: int) -> bool:
    try:
        return int(str(row.get("sequence_step") or "")) == sequence_step
    except ValueError:
        return False


def _insert_draft(
    client: Any,
    lead_id: str,
    draft: dict[str, Any],
    *,
    sequence_step: int,
) -> None:
    (
        client.table("outreach_drafts")
        .insert(
            {
                "lead_id": lead_id,
                "sequence_step": sequence_step,
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


def _followup_draft_for_channel(
    lead: dict[str, Any],
    score: dict[str, Any],
    channel: str,
    followup_step: int,
) -> dict[str, Any]:
    if channel == "email":
        return {
            "channel": "email",
            "subject": _followup_email_subject(lead, followup_step),
            "body": _followup_email_body(lead, score, followup_step),
        }
    if channel == "linkedin":
        return {
            "channel": "linkedin",
            "subject": None,
            "body": _followup_linkedin_body(lead, score, followup_step),
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


def _followup_email_subject(lead: dict[str, Any], followup_step: int) -> str:
    company = _text(lead.get("company_name"), "your team")
    if followup_step == 4:
        return f"Should I close the loop on {company}?"
    return f"Following up on {company}"


def _followup_email_body(
    lead: dict[str, Any],
    score: dict[str, Any],
    followup_step: int,
) -> str:
    person = _first_name(lead.get("person_name")) or "there"
    company = _text(lead.get("company_name"), "your team")
    focus = _short_focus(lead, score)

    if followup_step == 2:
        lines = [
            f"Hi {person},",
            "",
            f"Just wanted to bump my earlier note about {company}.",
            f"Datamart may be useful if {focus} or practical engineering capacity is on the roadmap.",
            "",
            "Would it be worth a quick 10-minute conversation?",
            "",
            "Best,",
            "Datamart",
        ]
    elif followup_step == 3:
        lines = [
            f"Hi {person},",
            "",
            f"One more thought for {company}: teams often reach a point where reducing manual work, improving workflows, or scaling engineering capacity becomes easier with a focused outside team.",
            "Datamart helps with AI agents, CRM/workflow automation, and SaaS/backend engineering.",
            "",
            "Would it be worth a quick 10-minute conversation?",
            "",
            "Best,",
            "Datamart",
        ]
    elif followup_step == 4:
        lines = [
            f"Hi {person},",
            "",
            f"I do not want to keep nudging if this is not a priority for {company} right now.",
            "Should I close the loop, or is there someone else who owns software automation or engineering capacity?",
            "",
            "Best,",
            "Datamart",
        ]
    else:
        raise ValueError("Follow-up step must be 2, 3, or 4")

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


def _followup_linkedin_body(
    lead: dict[str, Any],
    score: dict[str, Any],
    followup_step: int,
) -> str:
    person = _first_name(lead.get("person_name")) or "there"
    company = _text(lead.get("company_name"), "your team")
    focus = _short_focus(lead, score)

    if followup_step == 2:
        return (
            f"Hi {person}, quick bump on my earlier note. "
            "Would you be open to one brief idea?"
        )
    if followup_step == 3:
        return (
            f"Hi {person}, if {focus} is relevant for {company}, "
            "would a short Datamart idea be useful?"
        )
    if followup_step == 4:
        return (
            f"Hi {person}, should I close the loop for now, "
            "or would it be better to reconnect later?"
        )
    raise ValueError("Follow-up step must be 2, 3, or 4")


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
