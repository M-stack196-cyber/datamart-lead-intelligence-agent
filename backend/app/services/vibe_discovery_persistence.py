from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.qualified_event_intelligence import (
    QualifiedProspectIntelligence,
)
from app.services.outreach import OutreachDraftEngine
from app.services.vibe_prefilter import prefilter_prospect
from app.services.vibe_identity import prospect_identities


@dataclass(frozen=True)
class PersistedLead:
    lead_id: str
    business_id: str | None
    linkedin_url: str | None
    email: str | None
    pipeline_status: str = ""


@dataclass(frozen=True)
class DiscoveryPersistenceResult:
    leads: list[PersistedLead]
    stored_count: int
    duplicate_count: int
    evidence_count: int
    draft_count: int
    errors: list[str]


def _prospect_payload(
    item: QualifiedProspectIntelligence,
) -> dict[str, Any]:
    prospect = dict(
        item.scored_prospect.prospect
    )

    if item.business_id:
        prospect["vibe_business_id"] = (
            item.business_id
        )

    return prospect


def _match_stored_lead(
    prospect: dict[str, Any],
    stored: list[dict[str, Any]],
) -> dict[str, Any] | None:
    identities = prospect_identities(prospect)
    for row in stored:
        if isinstance(row, dict) and identities & prospect_identities(row):
            return row
    return None


def persist_discovery_intelligence(
    client: Any,
    items: list[
        QualifiedProspectIntelligence
    ],
    *,
    generate_drafts: bool = True,
) -> DiscoveryPersistenceResult:
    rejected_errors = []
    accepted_items = []
    seen: set[tuple[str, ...]] = set()
    local_duplicates = 0
    for item in items:
        admission = prefilter_prospect(item.scored_prospect.prospect)
        if not admission.accepted or item.scored_prospect.pipeline_status == "rejected":
            rejected_errors.extend(admission.rejection_reasons or item.scored_prospect.score.hard_stops)
        else:
            identities = prospect_identities(_prospect_payload(item))
            if identities & seen:
                seen.update(identities)
                local_duplicates += 1
                continue
            seen.update(identities)
            accepted_items.append(item)
    items = accepted_items
    if not items:
        return DiscoveryPersistenceResult([], 0, 0, 0, 0, rejected_errors)

    rows = [
        _prospect_payload(item)
        for item in items
    ]

    ingest_response: dict[str, Any] = {
        "inserted": 0,
        "updated": 0,
        "duplicates": 0,
        "rejected": 0,
        "errors": [],
        "leads": [],
    }

    for start in range(0, len(rows), 100):
        batch_response = (
            client
            .rpc(
                "ingest_vibe_discovered_leads",
                {"rows": rows[start:start + 100]},
            )
            .execute()
            .data
        )

        if not isinstance(batch_response, dict):
            raise RuntimeError("Unexpected Vibe intake response")

        ingest_response["duplicates"] += int(
            batch_response.get("duplicates", batch_response.get("updated", 0)) or 0
        )
        for count_field in ("inserted", "updated", "rejected"):
            ingest_response[count_field] += int(batch_response.get(count_field) or 0)
        for list_field in ("errors", "leads"):
            values = batch_response.get(list_field) or []
            if isinstance(values, list):
                ingest_response[list_field].extend(values)

    stored_rows = ingest_response.get(
        "leads",
        [],
    )

    if not isinstance(
        stored_rows,
        list,
    ):
        raise RuntimeError(
            "Vibe intake response did not "
            "contain lead mappings"
        )

    persisted: list[PersistedLead] = []
    errors: list[str] = [
        str(item.get("reason") or "A provider prospect could not be stored")
        for item in (ingest_response.get("errors") or [])
        if isinstance(item, dict)
    ]
    errors.extend(rejected_errors)
    evidence_count = 0
    draft_count = 0

    processed_ids: set[str] = set()
    for item in items:
        prospect = _prospect_payload(item)

        stored = _match_stored_lead(
            prospect,
            stored_rows,
        )

        if stored is None:
            errors.append("A discovered prospect was not mapped to a stored lead")
            continue

        lead_id = stored.get("lead_id")

        if not isinstance(
            lead_id,
            str,
        ) or not lead_id.strip():
            errors.append("A discovery mapping did not contain a valid lead ID")
            continue

        # The ingest RPC returns one mapping per input row, including duplicates.
        # Existing leads must not reappear in output or receive repeat drafts.
        if stored.get("duplicate") or lead_id in processed_ids:
            continue
        processed_ids.add(lead_id)

        score_payload = (
            item
            .scored_prospect
            .score
            .model_dump(mode="json")
        )

        intent_payload = asdict(
            item.intent
        )

        try:
            intelligence_response = (
                client
                .rpc(
                    "persist_vibe_discovery_intelligence",
                    {
                        "target_lead_id": lead_id,
                        "score_result": score_payload,
                        "intent_result": intent_payload,
                        "evidence_items": item.evidence,
                    },
                )
                .execute()
                .data
            )
        except Exception as exc:
            errors.append(
                f"Lead {lead_id} intelligence persistence failed: {type(exc).__name__}"
            )
            continue

        if not isinstance(intelligence_response, dict):
            errors.append(f"Lead {lead_id} returned an invalid persistence response")
            continue

        stored_evidence_ids = intelligence_response.get("evidence_ids") or []
        if not isinstance(stored_evidence_ids, list):
            stored_evidence_ids = []
        evidence_count += int(intelligence_response.get("evidence_count") or 0)

        if (
            generate_drafts
            and item.scored_prospect.pipeline_status == "qualified"
            and not item.scored_prospect.score.hard_stops
            and item.evidence
            and stored_evidence_ids
        ):
            grounded_evidence = [
                {**evidence, "id": evidence_id}
                for evidence, evidence_id in zip(item.evidence, stored_evidence_ids)
            ]
            try:
                draft = OutreachDraftEngine.draft(
                    prospect,
                    grounded_evidence,
                    channel="email",
                    persona=item.scored_prospect.score.persona,
                )
                (
                    client
                    .rpc(
                        "create_automatic_vibe_outreach_draft",
                        {
                            "target_lead_id": lead_id,
                            "draft_subject": draft["subject"],
                            "draft_body": draft["body"],
                            "draft_evidence_ids": draft["evidence_ids"],
                        },
                    )
                    .execute()
                )
                draft_count += 1
            except Exception as exc:
                errors.append(
                    f"Lead {lead_id} outreach draft was not created: {type(exc).__name__}"
                )

        persisted.append(
            PersistedLead(
                lead_id=lead_id,
                pipeline_status=item.scored_prospect.pipeline_status,
                business_id=(
                    item.business_id
                ),
                linkedin_url=(
                    prospect.get(
                        "linkedin_url"
                    )
                ),
                email=(
                    prospect.get(
                        "email"
                    )
                ),
            )
        )

    return DiscoveryPersistenceResult(
        leads=persisted,
        stored_count=int(ingest_response.get("inserted") or 0),
        duplicate_count=local_duplicates + int(ingest_response.get("duplicates") or 0),
        evidence_count=evidence_count,
        draft_count=draft_count,
        errors=errors,
    )


def persist_qualified_intelligence(
    client: Any,
    items: list[QualifiedProspectIntelligence],
) -> list[PersistedLead]:
    """Backward-compatible wrapper for the original discovery persistence API."""
    return persist_discovery_intelligence(
        client,
        items,
        generate_drafts=False,
    ).leads
