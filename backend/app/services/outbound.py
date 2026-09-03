from __future__ import annotations

import hashlib
from collections.abc import Iterable

from app.schemas.outbound import OutreachSequenceStep, SuppressionEntry


MANAGER_ROLES = {"admin", "manager"}
SUPPRESSION_ROLES = {"admin"}


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def find_suppression_entry(email: str, suppressions: Iterable[SuppressionEntry]) -> SuppressionEntry | None:
    normalized_email = normalize_email(email)
    for entry in suppressions:
        if entry.is_active and entry.normalized_email == normalized_email:
            return entry
    return None


def is_suppressed(email: str, suppressions: Iterable[SuppressionEntry]) -> bool:
    return find_suppression_entry(email, suppressions) is not None


def ordered_sequence_steps(steps: Iterable[OutreachSequenceStep]) -> list[OutreachSequenceStep]:
    ordered_steps = sorted(steps, key=lambda step: step.step_number)
    step_numbers = [step.step_number for step in ordered_steps]
    if len(step_numbers) != len(set(step_numbers)):
        raise ValueError("sequence step numbers must be unique")
    return ordered_steps


def build_idempotency_key(
    *,
    lead_id: str,
    sequence_id: str,
    step_number: int,
    recipient_email: str,
    provider_name: str = "mock",
) -> str:
    material = "|".join(
        [provider_name, lead_id, sequence_id, str(step_number), normalize_email(recipient_email)]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def can_manage_outbound_sequences(role: str | None) -> bool:
    return role in MANAGER_ROLES


def can_manage_outbound_suppression(role: str | None) -> bool:
    return role in SUPPRESSION_ROLES


def can_manage_crm_sync(role: str | None) -> bool:
    return role in MANAGER_ROLES


def can_view_outbound_records(role: str | None) -> bool:
    return role in MANAGER_ROLES
