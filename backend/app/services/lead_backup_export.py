from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import StringIO
from typing import Any


LEAD_COLUMNS = [
    "lead_id",
    "lead_source",
    "source_id",
    "status",
    "person_name",
    "title",
    "company_name",
    "email",
    "phone",
    "linkedin_url",
    "company_url",
    "country",
    "industry",
    "employee_count",
    "revenue",
    "job_level",
    "created_at",
    "source_captured_at",
]

SCORE_COLUMNS = [
    "icp_score",
    "disposition",
    "tier",
    "persona",
    "review_reasons",
    "hard_stops",
    "evaluations",
    "intent_score",
    "intent_level",
    "intent_reasons",
    "scored_at",
]

SUMMARY_COLUMNS = [
    "total_drafts",
    "email_draft_count",
    "linkedin_draft_count",
    "approved_count",
    "rejected_count",
    "draft_count",
    "manually_sent_count",
    "system_sent_count",
    "lead_replied",
    "latest_reply_at",
]

SEQUENCE_COLUMNS = [
    column
    for channel in ("email", "linkedin")
    for step in range(1, 5)
    for column in (
        ([f"{channel}_step_{step}_subject"] if channel == "email" else [])
        + [
            f"{channel}_step_{step}_body",
            f"{channel}_step_{step}_status",
            f"{channel}_step_{step}_review_notes",
            f"{channel}_step_{step}_reviewed_at",
        ]
    )
]

CSV_COLUMNS = LEAD_COLUMNS + SCORE_COLUMNS + SUMMARY_COLUMNS + SEQUENCE_COLUMNS

PREVIEW_COLUMNS = [
    "lead_id",
    "lead_source",
    "source_id",
    "status",
    "person_name",
    "title",
    "company_name",
    "email",
    "phone",
    "linkedin_url",
    "company_url",
    "country",
    "industry",
    "employee_count",
    "created_at",
    "source_captured_at",
    "icp_score",
    "disposition",
    "tier",
    "persona",
    "review_reasons",
    "hard_stops",
    "intent_score",
    "intent_level",
    "total_drafts",
    "email_draft_count",
    "linkedin_draft_count",
    "approved_count",
    "rejected_count",
    "draft_count",
    "manually_sent_count",
    "system_sent_count",
    "lead_replied",
    "latest_reply_at",
] + [
    f"{channel}_step_{step}_status"
    for channel in ("email", "linkedin")
    for step in range(1, 5)
]


@dataclass(frozen=True)
class LeadBackupExport:
    filename: str
    content: str
    row_count: int
    content_type: str = "text/csv; charset=utf-8"


def build_lead_backup_rows(
    client: Any,
    *,
    source: str | None = None,
    status: str | None = None,
    limit: int = 1000,
) -> list[dict[str, str | int | bool]]:
    if limit < 1 or limit > 5000:
        raise ValueError("Lead backup export limit must be between 1 and 5000")

    leads = _fetch_leads(client, source=source, status=status, limit=limit)
    lead_ids = [str(lead["id"]) for lead in leads if lead.get("id")]
    scores = _latest_scores(client, lead_ids)
    drafts = _drafts_by_lead(client, lead_ids)
    replies = _replies_by_lead(client, lead_ids)
    sent_counts = _system_sent_counts(client, lead_ids)
    return [
        _row_for_lead(
            lead,
            score=scores.get(str(lead.get("id"))) or {},
            drafts=drafts.get(str(lead.get("id")), []),
            replies=replies.get(str(lead.get("id")), []),
            system_sent_count=sent_counts.get(str(lead.get("id")), 0),
        )
        for lead in leads
    ]


def build_lead_backup_csv(
    client: Any,
    *,
    source: str | None = None,
    status: str | None = None,
    limit: int = 1000,
) -> LeadBackupExport:
    rows = build_lead_backup_rows(client, source=source, status=status, limit=limit)

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    source_part = _filename_part(source or "all")
    return LeadBackupExport(
        filename=f"datamart-lead-backup-{source_part}-{date.today().isoformat()}.csv",
        content=output.getvalue(),
        row_count=len(rows),
    )


def build_lead_backup_preview(
    client: Any,
    *,
    source: str | None = None,
    status: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    rows = build_lead_backup_rows(client, source=source, status=status, limit=limit)
    return {
        "source": source or "all",
        "status": status or "all",
        "limit": limit,
        "total": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "leads": [_preview_row(row) for row in rows],
    }


def _fetch_leads(
    client: Any,
    *,
    source: str | None,
    status: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    query = client.table("leads").select("*").order("created_at", desc=True).limit(limit)
    if source and source != "all":
        query = query.eq("lead_source", source)
    if status and status != "all":
        query = query.eq("status", status)
    rows = query.execute().data or []
    return [row for row in rows if isinstance(row, dict)]


def _latest_scores(client: Any, lead_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not lead_ids:
        return {}
    rows = (
        client.table("lead_scores")
        .select("*")
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
        .select("*")
        .in_("lead_id", lead_ids)
        .order("sequence_step")
        .execute()
        .data
        or []
    )
    return _group_by_lead(rows)


def _replies_by_lead(client: Any, lead_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not lead_ids:
        return {}
    try:
        rows = (
            client.table("inbound_reply_events")
            .select("*")
            .in_("lead_id", lead_ids)
            .order("received_at", desc=True)
            .execute()
            .data
            or []
        )
    except Exception:
        return {}
    return _group_by_lead(rows)


def _system_sent_counts(client: Any, lead_ids: list[str]) -> dict[str, int]:
    if not lead_ids:
        return {}
    try:
        rows = (
            client.table("email_delivery_attempts")
            .select("lead_id,status")
            .in_("lead_id", lead_ids)
            .eq("status", "sent")
            .execute()
            .data
            or []
        )
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("lead_id"):
            lead_id = str(row["lead_id"])
            counts[lead_id] = counts.get(lead_id, 0) + 1
    return counts


def _group_by_lead(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("lead_id"):
            grouped.setdefault(str(row["lead_id"]), []).append(row)
    return grouped


def _row_for_lead(
    lead: dict[str, Any],
    *,
    score: dict[str, Any],
    drafts: list[dict[str, Any]],
    replies: list[dict[str, Any]],
    system_sent_count: int,
) -> dict[str, str | int | bool]:
    row: dict[str, str | int | bool] = {
        "lead_id": _string(lead.get("id")),
        "lead_source": _string(lead.get("lead_source")),
        "source_id": _string(lead.get("source_id")),
        "status": _string(lead.get("status")),
        "person_name": _string(lead.get("person_name")),
        "title": _string(lead.get("title")),
        "company_name": _string(lead.get("company_name")),
        "email": _string(lead.get("email")),
        "phone": _string(lead.get("phone")),
        "linkedin_url": _string(lead.get("linkedin_url")),
        "company_url": _string(lead.get("company_url")),
        "country": _string(lead.get("country")),
        "industry": _string(lead.get("industry")),
        "employee_count": _string(lead.get("employee_count")),
        "revenue": _string(lead.get("annual_revenue") or lead.get("revenue")),
        "job_level": _string(lead.get("job_level")),
        "created_at": _string(lead.get("created_at")),
        "source_captured_at": _string(lead.get("source_captured_at")),
        "icp_score": _string(score.get("score")),
        "disposition": _string(score.get("disposition")),
        "tier": _string(score.get("tier")),
        "persona": _string(score.get("persona")),
        "review_reasons": _jsonish(score.get("review_reasons")),
        "hard_stops": _jsonish(score.get("hard_stops")),
        "evaluations": _jsonish(score.get("evaluations")),
        "intent_score": _string(score.get("intent_score")),
        "intent_level": _string(score.get("intent_level")),
        "intent_reasons": _jsonish(score.get("intent_reasons")),
        "scored_at": _string(score.get("scored_at")),
        "total_drafts": len(drafts),
        "email_draft_count": sum(1 for draft in drafts if draft.get("channel") == "email"),
        "linkedin_draft_count": sum(1 for draft in drafts if draft.get("channel") == "linkedin"),
        "approved_count": _status_count(drafts, "approved"),
        "rejected_count": _status_count(drafts, "rejected"),
        "draft_count": _status_count(drafts, "draft"),
        "manually_sent_count": _manual_sent_count(drafts),
        "system_sent_count": system_sent_count + _status_count(drafts, "system_sent"),
        "lead_replied": bool(replies),
        "latest_reply_at": _string(_latest_reply_at(replies)),
    }

    for draft in drafts:
        channel = str(draft.get("channel") or "")
        try:
            step = int(str(draft.get("sequence_step") or ""))
        except ValueError:
            continue
        if channel not in {"email", "linkedin"} or step not in {1, 2, 3, 4}:
            continue
        prefix = f"{channel}_step_{step}"
        if channel == "email":
            row[f"{prefix}_subject"] = _string(draft.get("subject"))
        row[f"{prefix}_body"] = _string(draft.get("body"))
        row[f"{prefix}_status"] = _string(draft.get("status"))
        row[f"{prefix}_review_notes"] = _string(draft.get("review_notes"))
        row[f"{prefix}_reviewed_at"] = _string(draft.get("reviewed_at"))

    for column in CSV_COLUMNS:
        row.setdefault(column, "")
    return row


def _status_count(drafts: list[dict[str, Any]], status: str) -> int:
    return sum(1 for draft in drafts if str(draft.get("status") or "") == status)


def _manual_sent_count(drafts: list[dict[str, Any]]) -> int:
    return sum(
        1
        for draft in drafts
        if str(draft.get("status") or "") == "manual_sent"
        or (
            "manual" in str(draft.get("review_notes") or "").casefold()
            and str(draft.get("status") or "") == "approved"
        )
    )


def _latest_reply_at(replies: list[dict[str, Any]]) -> Any:
    values = [
        reply.get("received_at") or reply.get("created_at")
        for reply in replies
        if reply.get("received_at") or reply.get("created_at")
    ]
    return sorted(values, reverse=True)[0] if values else ""


def _jsonish(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return _jsonish(value)
    return str(value)


def _filename_part(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in value)
    return cleaned.strip("-") or "all"


def _preview_row(row: dict[str, str | int | bool]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for column in PREVIEW_COLUMNS:
        value = row.get(column, "")
        if column in {"review_reasons", "hard_stops"}:
            preview[column] = _parse_json_list(value)
        elif column in {
            "total_drafts",
            "email_draft_count",
            "linkedin_draft_count",
            "approved_count",
            "rejected_count",
            "draft_count",
            "manually_sent_count",
            "system_sent_count",
        }:
            preview[column] = int(value or 0)
        elif column == "lead_replied":
            preview[column] = bool(value)
        else:
            preview[column] = value
    return preview


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return [str(value)]
    return parsed if isinstance(parsed, list) else [parsed]
