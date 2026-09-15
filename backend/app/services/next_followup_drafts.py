from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.services.generic_outreach_drafts import (
    _draft_for_channel,
    _followup_draft_for_channel,
    _latest_score,
)
from app.services.sender_accounts import sender_for_manual_record


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
    message: str | None = None


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
    reply_wait_days: int | None = None,
    next_followup_decision_at: datetime | str | None = None,
    sender_account_id: str | None = None,
    sent_from_email: str | None = None,
) -> dict[str, Any]:
    draft = _draft_by_id(client, draft_id)
    if not draft:
        raise ValueError("Outreach draft not found")
    if str(draft.get("status") or "").casefold() in TERMINAL_STATUSES:
        raise ValueError("Rejected or archived drafts cannot be marked as manually sent")

    review_note = notes.strip() if notes else "Marked as manually sent outside the system."
    manual_sent_at = _parse_time(draft.get("manual_sent_at")) or _now()
    wait_payload = _reply_wait_payload(
        base_time=manual_sent_at,
        reply_wait_days=reply_wait_days,
        next_followup_decision_at=next_followup_decision_at,
        required=True,
    )
    stored_sender_account_id, stored_sent_from_email = sender_for_manual_record(
        client,
        sender_account_id=sender_account_id,
        sent_from_email=sent_from_email,
    )
    rows = (
        client.table("outreach_drafts")
        .update(
            {
                "status": "manual_sent",
                "reviewed_by": actor_id,
                "reviewed_at": _now_sql(),
                "review_notes": review_note,
                "manual_sent_at": _format_time(manual_sent_at),
                "sender_account_id": stored_sender_account_id,
                "sent_from_email": stored_sent_from_email,
                **wait_payload,
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
            "sender_account_id": stored_sender_account_id,
            "sent_from_email": stored_sent_from_email,
            "status_used": "manual_sent",
            "note": "Draft was manually sent outside the system and remains recorded for review history.",
        },
    )
    return rows[0]


def update_draft_reply_wait(
    client: Any,
    *,
    draft_id: str,
    actor_id: str,
    reply_wait_days: int | None = None,
    next_followup_decision_at: datetime | str | None = None,
) -> dict[str, Any]:
    draft = _draft_by_id(client, draft_id)
    if not draft:
        raise ValueError("Outreach draft not found")
    if not _is_sent_like(draft, set()):
        raise ValueError("Reply wait can only be set after a draft is sent or manually sent")
    if draft.get("followup_stopped_at"):
        raise ValueError("Follow-up is already stopped for this draft")

    sent_time = _sent_time(draft) or _now()
    now = _now()
    base_time = sent_time if sent_time > now else now
    payload = _reply_wait_payload(
        base_time=base_time,
        reply_wait_days=reply_wait_days,
        next_followup_decision_at=next_followup_decision_at,
        required=True,
    )
    rows = (
        client.table("outreach_drafts")
        .update(
            {
                **payload,
                "reviewed_by": actor_id,
                "reviewed_at": _now_sql(),
            }
        )
        .eq("id", draft_id)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError("Outreach draft not found")
    return rows[0]


def stop_draft_followup(
    client: Any,
    *,
    draft_id: str,
    actor_id: str,
    reason: str = "Stopped by team decision.",
) -> dict[str, Any]:
    draft = _draft_by_id(client, draft_id)
    if not draft:
        raise ValueError("Outreach draft not found")
    if not _is_sent_like(draft, set()):
        raise ValueError("Follow-up can only be stopped after a draft is sent or manually sent")
    rows = (
        client.table("outreach_drafts")
        .update(
            {
                "followup_stopped_at": _now_sql(),
                "followup_stop_reason": reason.strip() or "Stopped by team decision.",
                "reviewed_by": actor_id,
                "reviewed_at": _now_sql(),
            }
        )
        .eq("id", draft_id)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError("Outreach draft not found")
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
        return NextFollowupChannelResult(
            channel=channel,
            created=False,
            reason="lead_replied",
            message="Lead replied — follow-up stopped",
        )

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
    latest_sent_draft = _draft_for_channel_step(drafts, channel, latest_sent_step)
    if not latest_sent_draft:
        return NextFollowupChannelResult(
            channel=channel,
            created=False,
            reason="previous_step_not_sent_or_approved",
        )
    if latest_sent_step >= 4:
        return NextFollowupChannelResult(channel=channel, created=False, reason="sequence_complete")
    wait_decision = _followup_wait_decision(latest_sent_draft)
    if wait_decision:
        return NextFollowupChannelResult(
            channel=channel,
            created=False,
            reason=wait_decision,
            sequence_step=latest_sent_step + 1,
            draft=latest_sent_draft,
            message=_followup_wait_message(latest_sent_draft, wait_decision),
        )

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
        .select(
            "id,lead_id,channel,subject,body,status,sequence_step,evidence_ids,review_notes,"
            "sent_at,manual_sent_at,reply_wait_days,next_followup_decision_at,"
            "followup_stopped_at,followup_stop_reason,sender_account_id,sent_from_email"
        )
        .eq("lead_id", lead_id)
        .execute()
        .data
        or []
    )
    return [row for row in rows if isinstance(row, dict)]


def _draft_by_id(client: Any, draft_id: str) -> dict[str, Any] | None:
    rows = (
        client.table("outreach_drafts")
        .select(
            "id,lead_id,channel,subject,body,status,sequence_step,evidence_ids,review_notes,"
            "sent_at,manual_sent_at,reply_wait_days,next_followup_decision_at,"
            "followup_stopped_at,followup_stop_reason,sender_account_id,sent_from_email"
        )
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


def _followup_wait_decision(draft: dict[str, Any]) -> str | None:
    if draft.get("followup_stopped_at"):
        return "followup_stopped"
    decision_at = _parse_time(draft.get("next_followup_decision_at"))
    if decision_at is None:
        return "reply_wait_not_set"
    if decision_at > _now():
        return "waiting_for_reply"
    return None


def _followup_wait_message(draft: dict[str, Any], reason: str) -> str:
    if reason == "followup_stopped":
        return "Follow-up stopped"
    if reason == "reply_wait_not_set":
        return "Reply wait period not set"
    decision_at = _parse_time(draft.get("next_followup_decision_at"))
    if decision_at is None:
        return "Reply wait period not set"
    return f"Waiting for reply until {_format_time(decision_at)}"


def _reply_wait_payload(
    *,
    base_time: datetime,
    reply_wait_days: int | None,
    next_followup_decision_at: datetime | str | None,
    required: bool,
) -> dict[str, Any]:
    if reply_wait_days is not None and next_followup_decision_at is not None:
        raise ValueError("Choose reply_wait_days or next_followup_decision_at, not both")
    if reply_wait_days is None and next_followup_decision_at is None:
        if required:
            raise ValueError("Reply wait period is required")
        return {}
    if reply_wait_days is not None:
        decision_at = base_time + timedelta(days=reply_wait_days)
        return {
            "reply_wait_days": reply_wait_days,
            "next_followup_decision_at": _format_time(decision_at),
        }

    decision_at = _parse_time(next_followup_decision_at)
    if decision_at is None:
        raise ValueError("next_followup_decision_at must be a valid ISO timestamp")
    if decision_at <= base_time:
        raise ValueError("next_followup_decision_at must be after the sent timestamp")
    return {
        "reply_wait_days": None,
        "next_followup_decision_at": _format_time(decision_at),
    }


def _sent_time(draft: dict[str, Any]) -> datetime | None:
    return _parse_time(draft.get("manual_sent_at")) or _parse_time(draft.get("sent_at"))


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    return _format_time(_now())


def _now() -> datetime:
    return datetime.now(timezone.utc)
