from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


DraftAction = str
ACTIVE_DRAFT_STATUSES = {"draft", "needs_edit", "approved", "manual_sent", "system_sent", "sent"}
TERMINAL_DRAFT_STATUSES = {"rejected", "archived", "cancelled"}


@dataclass(frozen=True)
class ReviewWorkspaceResult:
    source: str
    status: str
    limit: int
    leads: list[dict[str, Any]]


def review_workspace_leads(
    client: Any,
    *,
    source: str = "apollo_csv",
    status: str = "review",
    limit: int = 50,
    include_drafts: bool = True,
) -> ReviewWorkspaceResult:
    if limit < 1 or limit > 200:
        raise ValueError("Review workspace limit must be between 1 and 200")

    query = (
        client.table("leads")
        .select(
            "id,person_name,title,company_name,email,phone,linkedin_url,company_url,"
            "country,industry,employee_count,lead_source,source_id,status,created_at,"
            "source_captured_at"
        )
        .eq("lead_source", source)
        .eq("status", status)
        .order("source_captured_at", desc=True)
        .limit(limit)
    )
    leads = [row for row in (query.execute().data or []) if isinstance(row, dict)]
    lead_ids = [str(lead["id"]) for lead in leads if lead.get("id")]

    scores = _latest_scores_by_lead(client, lead_ids)
    drafts = _drafts_by_lead(client, lead_ids) if include_drafts else {}
    replied_lead_ids = _replied_lead_ids(client, lead_ids)

    return ReviewWorkspaceResult(
        source=source,
        status=status,
        limit=limit,
        leads=[
            {
                **lead,
                "latest_score": scores.get(str(lead.get("id"))) or None,
                "has_replies": str(lead.get("id")) in replied_lead_ids,
                "outreach_drafts": _group_drafts(drafts.get(str(lead.get("id")), [])),
            }
            for lead in leads
        ],
    )


def review_outreach_draft_status(
    client: Any,
    *,
    draft_id: str,
    action: DraftAction,
    review_notes: str,
    actor_id: str,
) -> dict[str, Any]:
    normalized_action = action.strip().casefold()
    if normalized_action not in {"approve", "reject", "needs_edit"}:
        raise ValueError("Draft review action must be approve, reject, or needs_edit")
    if not review_notes.strip():
        raise ValueError("Review notes are required")

    status = {
        "approve": "approved",
        "reject": "rejected",
        "needs_edit": "needs_edit",
    }[normalized_action]

    rows = (
        client.table("outreach_drafts")
        .update(
            {
                "status": status,
                "reviewed_by": actor_id,
                "review_notes": review_notes.strip(),
                "reviewed_at": None if normalized_action == "needs_edit" else _now_sql(),
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


def _latest_scores_by_lead(client: Any, lead_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not lead_ids:
        return {}
    rows = (
        client.table("lead_scores")
        .select(
            "lead_id,score,disposition,tier,persona,hard_stops,review_reasons,"
            "evaluations,intent_score,intent_level,intent_reasons,scored_at"
        )
        .in_("lead_id", lead_ids)
        .order("scored_at", desc=True)
        .execute()
        .data
        or []
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        lead_id = str(row.get("lead_id") or "")
        if lead_id and lead_id not in latest:
            latest[lead_id] = row
    return latest


def _drafts_by_lead(client: Any, lead_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not lead_ids:
        return {}
    rows = (
        client.table("outreach_drafts")
        .select(
            "id,lead_id,channel,subject,body,status,sequence_step,evidence_ids,"
            "created_by,reviewed_by,reviewed_at,review_notes,created_at,updated_at,"
            "sent_at,manual_sent_at,reply_wait_days,next_followup_decision_at,"
            "followup_stopped_at,followup_stop_reason"
        )
        .in_("lead_id", lead_ids)
        .order("sequence_step")
        .execute()
        .data
        or []
    )
    drafts: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("lead_id"):
            drafts.setdefault(str(row["lead_id"]), []).append(row)
    return drafts


def _replied_lead_ids(client: Any, lead_ids: list[str]) -> set[str]:
    if not lead_ids:
        return set()
    try:
        rows = (
            client.table("inbound_reply_events")
            .select("lead_id")
            .in_("lead_id", lead_ids)
            .execute()
            .data
            or []
        )
    except Exception:
        return set()
    return {str(row.get("lead_id")) for row in rows if isinstance(row, dict) and row.get("lead_id")}


def _group_drafts(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any] | None]]:
    grouped: dict[str, Any] = {
        "email": {f"step_{step}": None for step in range(1, 5)},
        "linkedin": {f"step_{step}": None for step in range(1, 5)},
        "archived": [],
    }
    for row in rows:
        channel = str(row.get("channel") or "")
        try:
            step = int(str(row.get("sequence_step") or ""))
        except ValueError:
            continue
        if channel not in {"email", "linkedin"} or step not in {1, 2, 3, 4}:
            continue
        status = str(row.get("status") or "")
        if status in TERMINAL_DRAFT_STATUSES:
            grouped["archived"].append(row)
            continue
        if status in ACTIVE_DRAFT_STATUSES:
            existing = grouped[channel][f"step_{step}"]
            if existing is None or _draft_sort_key(row) > _draft_sort_key(existing):
                grouped[channel][f"step_{step}"] = row
    return grouped


def _draft_sort_key(row: dict[str, Any]) -> str:
    return str(row.get("updated_at") or row.get("created_at") or "")


def _now_sql() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
