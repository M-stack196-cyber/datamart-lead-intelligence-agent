from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.services.generic_outreach_drafts import _draft_for_channel, _latest_score


ChannelRequest = Literal["email", "linkedin", "both"]
DraftChannel = Literal["email", "linkedin"]

ACTIVE_DRAFT_STATUSES = {"draft", "needs_edit", "approved", "manual_sent", "system_sent", "sent"}
TERMINAL_DRAFT_STATUSES = {"rejected", "archived", "cancelled"}


@dataclass(frozen=True)
class PrimaryDraftChannelResult:
    channel: str
    created: bool
    reason: str
    sequence_step: int = 1
    draft: dict[str, Any] | None = None


@dataclass(frozen=True)
class PrimaryDraftResult:
    lead_id: str
    source: str
    results: dict[str, PrimaryDraftChannelResult]


def create_primary_outreach_draft(
    client: Any,
    *,
    lead_id: str,
    actor_id: str | None = None,
    channel: ChannelRequest = "both",
    source: str = "apollo_csv",
) -> PrimaryDraftResult:
    lead = _lead_for_source(client, lead_id, source)
    if not lead:
        raise ValueError("Lead was not found for the requested source")

    drafts = _drafts_for_lead(client, lead_id)
    score = _latest_score(client, lead_id)
    results: dict[str, PrimaryDraftChannelResult] = {}
    for requested_channel in _requested_channels(channel):
        results[requested_channel] = _primary_for_channel(
            client,
            lead,
            score,
            drafts,
            requested_channel,
            actor_id=actor_id,
        )
    return PrimaryDraftResult(lead_id=lead_id, source=source, results=results)


def _primary_for_channel(
    client: Any,
    lead: dict[str, Any],
    score: dict[str, Any],
    drafts: list[dict[str, Any]],
    channel: DraftChannel,
    *,
    actor_id: str | None,
) -> PrimaryDraftChannelResult:
    existing = _active_primary_draft(drafts, channel)
    if existing:
        return PrimaryDraftChannelResult(
            channel=channel,
            created=False,
            reason="existing_draft",
            draft=existing,
        )

    terminal = _terminal_primary_draft(drafts, channel)
    if terminal:
        reactivated = _reactivate_terminal_primary_draft(client, terminal, lead, score, channel)
        return PrimaryDraftChannelResult(
            channel=channel,
            created=True,
            reason="reactivated_existing_terminal_draft",
            draft=reactivated,
        )

    draft = _draft_for_channel(lead, score, channel)
    payload = {
        "lead_id": lead["id"],
        "sequence_step": 1,
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
    return PrimaryDraftChannelResult(
        channel=channel,
        created=True,
        reason="created_primary_draft",
        draft=created,
    )


def _reactivate_terminal_primary_draft(
    client: Any,
    draft: dict[str, Any],
    lead: dict[str, Any],
    score: dict[str, Any],
    channel: DraftChannel,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "draft",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_notes": "Reactivated as primary outreach draft by team request.",
    }
    if not str(draft.get("body") or "").strip():
        regenerated = _draft_for_channel(lead, score, channel)
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


def _active_primary_draft(drafts: list[dict[str, Any]], channel: DraftChannel) -> dict[str, Any] | None:
    return _draft_for_channel_status(drafts, channel, ACTIVE_DRAFT_STATUSES)


def _terminal_primary_draft(drafts: list[dict[str, Any]], channel: DraftChannel) -> dict[str, Any] | None:
    return _draft_for_channel_status(drafts, channel, TERMINAL_DRAFT_STATUSES)


def _draft_for_channel_status(
    drafts: list[dict[str, Any]],
    channel: DraftChannel,
    statuses: set[str],
) -> dict[str, Any] | None:
    for draft in drafts:
        if (
            str(draft.get("channel") or "") == channel
            and _step(draft) == 1
            and str(draft.get("status") or "").casefold() in statuses
        ):
            return draft
    return None


def _step(draft: dict[str, Any]) -> int | None:
    try:
        return int(str(draft.get("sequence_step") or ""))
    except ValueError:
        return None


def _requested_channels(channel: ChannelRequest) -> list[DraftChannel]:
    if channel == "both":
        return ["email", "linkedin"]
    if channel in {"email", "linkedin"}:
        return [channel]
    raise ValueError("Channel must be email, linkedin, or both")
