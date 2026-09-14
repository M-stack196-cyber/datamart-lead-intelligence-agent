from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.services.generic_outreach_drafts import (
    _draft_for_channel,
    _followup_draft_for_channel,
    _latest_score,
)


ChannelRequest = Literal["email", "linkedin", "both"]
DraftChannel = Literal["email", "linkedin"]

SENT_LIKE_STATUSES = {"approved", "sent", "sent_manually", "manual_sent", "system_sent", "delivered"}
TERMINAL_STATUSES = {"rejected", "cancelled", "archived"}
BAD_PRIMARY_PHRASES = ("review-only note", "send a brief idea for review")


@dataclass(frozen=True)
class NextFollowupChannelResult:
    channel: str
    created: bool
    reason: str
    sequence_step: int | None = None
    draft: dict[str, Any] | None = None


@dataclass(frozen=True)
class NextFollowupResult:
    lead_id: str
    source: str
    results: dict[str, NextFollowupChannelResult]


@dataclass(frozen=True)
class MaintenanceResult:
    source: str
    dry_run: bool
    scanned: int
    updated: int
    counts: dict[str, int]
    draft_ids: list[str]
    errors: list[str]


def create_next_followup_draft(
    client: Any,
    *,
    lead_id: str,
    actor_id: str | None = None,
    channel: ChannelRequest = "both",
    source: str = "apollo_csv",
) -> NextFollowupResult:
    channels = _requested_channels(channel)
    lead = _lead_for_source(client, lead_id, source)
    if not lead:
        raise ValueError("Lead was not found for the requested source")

    drafts = _drafts_for_lead(client, lead_id)
    sent_attempt_draft_ids = _sent_attempt_draft_ids(client, lead_id)
    score = _latest_score(client, lead_id)
    lead_replied = has_lead_replied(client, lead_id)

    results: dict[str, NextFollowupChannelResult] = {}
    for requested_channel in channels:
        results[requested_channel] = _next_for_channel(
            client,
            lead,
            score,
            drafts,
            sent_attempt_draft_ids,
            requested_channel,
            lead_replied=lead_replied,
            actor_id=actor_id,
        )

    return NextFollowupResult(lead_id=lead_id, source=source, results=results)


def mark_draft_manually_sent(
    client: Any,
    *,
    draft_id: str,
    actor_id: str,
    notes: str | None = None,
) -> dict[str, Any]:
    draft = _draft_by_id(client, draft_id)
    if not draft:
        raise ValueError("Outreach draft not found")
    if str(draft.get("status") or "").casefold() in TERMINAL_STATUSES:
        raise ValueError("Rejected or archived drafts cannot be marked as manually sent")

    review_note = notes.strip() if notes else "Marked as manually sent outside the system."
    rows = (
        client.table("outreach_drafts")
        .update(
            {
                "status": "manual_sent",
                "reviewed_by": actor_id,
                "reviewed_at": _now_sql(),
                "review_notes": review_note,
            }
        )
        .eq("id", draft_id)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError("Outreach draft not found")

    _insert_audit_event(
        client,
        actor_id=actor_id,
        action="manual_outreach_marked_sent",
        entity_type="outreach_draft",
        entity_id=draft_id,
        details={
            "lead_id": draft.get("lead_id"),
            "channel": draft.get("channel"),
            "sequence_step": draft.get("sequence_step"),
            "status_used": "manual_sent",
            "note": "Draft was manually sent outside the system and remains recorded for review history.",
        },
    )
    return rows[0]


def has_lead_replied(client: Any, lead_id: str) -> bool:
    try:
        rows = (
            client.table("inbound_reply_events")
            .select("id")
            .eq("lead_id", lead_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        return False
    return bool(rows)


def archive_precreated_followup_drafts(
    client: Any,
    *,
    source: str = "apollo_csv",
    dry_run: bool = True,
) -> MaintenanceResult:
    leads = _leads_for_source(client, source)
    scanned = 0
    updated = 0
    counts: dict[str, int] = {}
    draft_ids: list[str] = []
    errors: list[str] = []

    for lead in leads:
        lead_id = str(lead.get("id") or "")
        if not lead_id:
            continue
        drafts = _drafts_for_lead(client, lead_id)
        sent_attempt_ids = _sent_attempt_draft_ids(client, lead_id)

        for draft in drafts:
            channel = str(draft.get("channel") or "")
            try:
                step = int(str(draft.get("sequence_step") or ""))
            except ValueError:
                continue
            if step not in {2, 3, 4} or str(draft.get("status") or "") != "draft":
                continue
            scanned += 1
            if _has_sent_like_step(drafts, sent_attempt_ids, channel, step - 1):
                continue

            key = f"step_{step}_{channel}"
            counts[key] = counts.get(key, 0) + 1
            draft_ids.append(str(draft.get("id") or ""))
            if dry_run:
                continue
            try:
                _archive_draft(client, str(draft["id"]))
                updated += 1
            except Exception as exc:
                errors.append(f"Draft {draft.get('id')} was not archived: {type(exc).__name__}")

    return MaintenanceResult(
        source=source,
        dry_run=dry_run,
        scanned=scanned,
        updated=updated,
        counts=counts,
        draft_ids=draft_ids,
        errors=errors,
    )


def refresh_bad_primary_drafts(
    client: Any,
    *,
    source: str = "apollo_csv",
    dry_run: bool = True,
) -> MaintenanceResult:
    leads = _leads_for_source(client, source)
    scanned = 0
    updated = 0
    counts: dict[str, int] = {}
    draft_ids: list[str] = []
    errors: list[str] = []

    for lead in leads:
        lead_id = str(lead.get("id") or "")
        if not lead_id:
            continue
        score = _latest_score(client, lead_id)
        for draft in _drafts_for_lead(client, lead_id):
            if not _is_bad_primary_draft(draft):
                continue
            scanned += 1
            channel = str(draft.get("channel") or "")
            if channel not in {"email", "linkedin"}:
                continue
            regenerated = _draft_for_channel(lead, score, channel)
            counts[channel] = counts.get(channel, 0) + 1
            draft_ids.append(str(draft.get("id") or ""))
            if dry_run:
                continue
            try:
                _update_draft_copy(
                    client,
                    str(draft["id"]),
                    subject=regenerated["subject"],
                    body=regenerated["body"],
                )
                updated += 1
            except Exception as exc:
                errors.append(f"Draft {draft.get('id')} was not refreshed: {type(exc).__name__}")

    return MaintenanceResult(
        source=source,
        dry_run=dry_run,
        scanned=scanned,
        updated=updated,
        counts=counts,
        draft_ids=draft_ids,
        errors=errors,
    )


def _next_for_channel(
    client: Any,
    lead: dict[str, Any],
    score: dict[str, Any],
    drafts: list[dict[str, Any]],
    sent_attempt_draft_ids: set[str],
    channel: DraftChannel,
    *,
    lead_replied: bool,
    actor_id: str | None,
) -> NextFollowupChannelResult:
    if lead_replied:
        return NextFollowupChannelResult(channel=channel, created=False, reason="lead_replied")

    sent_steps = [
        _step(draft)
        for draft in drafts
        if str(draft.get("channel") or "") == channel
        and _is_sent_like(draft, sent_attempt_draft_ids)
    ]
    latest_sent_step = max([step for step in sent_steps if step is not None], default=0)
    if latest_sent_step < 1:
        return NextFollowupChannelResult(
            channel=channel,
            created=False,
            reason="previous_step_not_sent_or_approved",
        )
    if latest_sent_step >= 4:
        return NextFollowupChannelResult(channel=channel, created=False, reason="sequence_complete")

    next_step = latest_sent_step + 1
    existing = _draft_for_channel_step(drafts, channel, next_step)
    if existing:
        return NextFollowupChannelResult(
            channel=channel,
            created=False,
            reason="existing_draft",
            sequence_step=next_step,
            draft=existing,
        )
    terminal_existing = _terminal_draft_for_channel_step(drafts, channel, next_step)
    if terminal_existing:
        reactivated = _reactivate_terminal_followup_draft(
            client,
            terminal_existing,
            lead,
            score,
            channel,
            next_step,
        )
        return NextFollowupChannelResult(
            channel=channel,
            created=True,
            reason="reactivated_existing_terminal_draft",
            sequence_step=next_step,
            draft=reactivated,
        )

    draft = _followup_draft_for_channel(lead, score, channel, next_step)
    payload = {
        "lead_id": lead["id"],
        "sequence_step": next_step,
        "channel": draft["channel"],
        "subject": draft["subject"],
        "body": draft["body"],
        "status": "draft",
        "evidence_ids": [],
        "created_by": actor_id,
        "reviewed_by": None,
        "reviewed_at": None,
        "review_notes": None,
    }
    rows = client.table("outreach_drafts").insert(payload).execute().data or []
    created = rows[0] if rows and isinstance(rows[0], dict) else payload
    return NextFollowupChannelResult(
        channel=channel,
        created=True,
        reason="created",
        sequence_step=next_step,
        draft=created,
    )


def _lead_for_source(client: Any, lead_id: str, source: str) -> dict[str, Any] | None:
    rows = (
        client.table("leads")
        .select(
            "id,person_name,title,company_name,company_url,linkedin_url,email,"
            "country,industry,lead_source,status,raw_source_data,source_captured_at"
        )
        .eq("id", lead_id)
        .eq("lead_source", source)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows and isinstance(rows[0], dict) else None


def _leads_for_source(client: Any, source: str) -> list[dict[str, Any]]:
    rows = (
        client.table("leads")
        .select(
            "id,person_name,title,company_name,company_url,linkedin_url,email,"
            "country,industry,lead_source,status,raw_source_data,source_captured_at"
        )
        .eq("lead_source", source)
        .execute()
        .data
        or []
    )
    return [row for row in rows if isinstance(row, dict)]


def _drafts_for_lead(client: Any, lead_id: str) -> list[dict[str, Any]]:
    rows = (
        client.table("outreach_drafts")
        .select("id,lead_id,channel,subject,body,status,sequence_step,evidence_ids,review_notes")
        .eq("lead_id", lead_id)
        .execute()
        .data
        or []
    )
    return [row for row in rows if isinstance(row, dict)]


def _draft_by_id(client: Any, draft_id: str) -> dict[str, Any] | None:
    rows = (
        client.table("outreach_drafts")
        .select("id,lead_id,channel,subject,body,status,sequence_step,evidence_ids,review_notes")
        .eq("id", draft_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows and isinstance(rows[0], dict) else None


def _sent_attempt_draft_ids(client: Any, lead_id: str) -> set[str]:
    try:
        rows = (
            client.table("email_delivery_attempts")
            .select("outreach_draft_id,status")
            .eq("lead_id", lead_id)
            .eq("status", "sent")
            .execute()
            .data
            or []
        )
    except Exception:
        return set()
    return {str(row.get("outreach_draft_id")) for row in rows if row.get("outreach_draft_id")}


def _requested_channels(channel: ChannelRequest) -> list[DraftChannel]:
    if channel == "both":
        return ["email", "linkedin"]
    if channel in {"email", "linkedin"}:
        return [channel]
    raise ValueError("Channel must be email, linkedin, or both")


def _has_sent_like_step(
    drafts: list[dict[str, Any]],
    sent_attempt_draft_ids: set[str],
    channel: str,
    sequence_step: int,
) -> bool:
    return any(
        str(draft.get("channel") or "") == channel
        and _step(draft) == sequence_step
        and _is_sent_like(draft, sent_attempt_draft_ids)
        for draft in drafts
    )


def _is_sent_like(draft: dict[str, Any], sent_attempt_draft_ids: set[str]) -> bool:
    return (
        str(draft.get("status") or "").casefold() in SENT_LIKE_STATUSES
        or str(draft.get("id") or "") in sent_attempt_draft_ids
    )


def _draft_for_channel_step(
    drafts: list[dict[str, Any]],
    channel: str,
    sequence_step: int,
) -> dict[str, Any] | None:
    for draft in drafts:
        if (
            str(draft.get("channel") or "") == channel
            and _step(draft) == sequence_step
            and not _is_terminal(draft)
        ):
            return draft
    return None


def _terminal_draft_for_channel_step(
    drafts: list[dict[str, Any]],
    channel: str,
    sequence_step: int,
) -> dict[str, Any] | None:
    for draft in drafts:
        if (
            str(draft.get("channel") or "") == channel
            and _step(draft) == sequence_step
            and _is_terminal(draft)
        ):
            return draft
    return None


def _reactivate_terminal_followup_draft(
    client: Any,
    draft: dict[str, Any],
    lead: dict[str, Any],
    score: dict[str, Any],
    channel: DraftChannel,
    sequence_step: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "draft",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_notes": "Reactivated as next follow-up draft by team after previous step was sent-like.",
    }
    if not str(draft.get("body") or "").strip():
        regenerated = _followup_draft_for_channel(lead, score, channel, sequence_step)
        payload["subject"] = regenerated["subject"]
        payload["body"] = regenerated["body"]

    rows = (
        client.table("outreach_drafts")
        .update(payload)
        .eq("id", draft["id"])
        .execute()
        .data
        or []
    )
    return rows[0] if rows and isinstance(rows[0], dict) else {**draft, **payload}


def _step(draft: dict[str, Any]) -> int | None:
    try:
        return int(str(draft.get("sequence_step") or ""))
    except ValueError:
        return None


def _is_bad_primary_draft(draft: dict[str, Any]) -> bool:
    if _step(draft) != 1 or str(draft.get("status") or "") != "draft":
        return False
    body = str(draft.get("body") or "").casefold()
    return any(phrase in body for phrase in BAD_PRIMARY_PHRASES)


def _is_terminal(draft: dict[str, Any]) -> bool:
    return str(draft.get("status") or "").casefold() in TERMINAL_STATUSES


def _archive_draft(client: Any, draft_id: str) -> None:
    (
        client.table("outreach_drafts")
        .update(
            {
                "status": "archived",
                "review_notes": "Archived by maintenance: pre-created follow-up before previous step was sent-like.",
            }
        )
        .eq("id", draft_id)
        .execute()
    )


def _update_draft_copy(client: Any, draft_id: str, *, subject: str | None, body: str) -> None:
    client.table("outreach_drafts").update({"subject": subject, "body": body}).eq("id", draft_id).execute()


def _insert_audit_event(
    client: Any,
    *,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict[str, Any],
) -> None:
    try:
        client.table("audit_log").insert(
            {
                "actor_id": actor_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": details,
            }
        ).execute()
    except Exception:
        return


def _now_sql() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
