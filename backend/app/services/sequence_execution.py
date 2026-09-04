from __future__ import annotations

import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.integrations.outbound import OutboundEmailRequest
from app.services import outreach_generation
from app.services import outreach_delivery
from app.services.outbound import (
    build_idempotency_key,
    can_manage_outbound_sequences,
)


_FALLBACK_SEQUENCE = {
    "id": "sequence-1",
    "external_id": "datamart-outbound-sequence-v1",
    "name": "Datamart Outreach Sequence",
    "is_enabled": True,
}

_FALLBACK_STEPS: list[dict[str, Any]] = [
    {
        "id": "step-1",
        "sequence_id": "sequence-1",
        "step_number": 1,
        "delay_days": 0,
        "subject_template": "A brief question about {{company_name}}",
        "message_template": (
            "Hi {{first_name}}, I reviewed the stored evidence for "
            "{{company_name}} and wanted to ask whether Datamart could "
            "help with the priorities already identified."
        ),
        "is_enabled": True,
    },
    {
        "id": "step-2",
        "sequence_id": "sequence-1",
        "step_number": 2,
        "delay_days": 3,
        "subject_template": "Following up on {{company_name}}",
        "message_template": (
            "Just following up on the earlier note. The evidence we "
            "have on {{company_name}} still suggests there may be a "
            "fit worth discussing."
        ),
        "is_enabled": True,
    },
    {
        "id": "step-3",
        "sequence_id": "sequence-1",
        "step_number": 3,
        "delay_days": 7,
        "subject_template": "One more follow-up for {{company_name}}",
        "message_template": (
            "I wanted to send one more brief follow-up in case this "
            "is still on your radar."
        ),
        "is_enabled": True,
    },
    {
        "id": "step-4",
        "sequence_id": "sequence-1",
        "step_number": 4,
        "delay_days": 14,
        "subject_template": "Closing the loop on {{company_name}}",
        "message_template": (
            "I will close the loop after this note, but I am happy to "
            "reconnect if the timing becomes better."
        ),
        "is_enabled": True,
    },
]


def _now_dt() -> datetime:
    return datetime.now(tz=UTC)


def _iso(value: datetime) -> str:
    return (
        value.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = value.strip().replace(
        "Z",
        "+00:00",
    )

    try:
        parsed = datetime.fromisoformat(
            normalized
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=UTC
        )

    return parsed.astimezone(UTC)


def _uses_fallback(
    settings: Settings,
) -> bool:
    return outreach_delivery._uses_fallback(
        settings
    )


def _client(settings: Settings):
    return outreach_delivery._client(
        settings
    )


def _provider_name(
    settings: Settings,
) -> str:
    return (
        settings.outbound_email_provider
        or "mock"
    ).strip().casefold()


def _sequence_steps(
    settings: Settings,
    sequence_id: str,
) -> list[dict[str, Any]]:
    if _uses_fallback(settings):
        return [
            deepcopy(step)
            for step in _FALLBACK_STEPS
            if (
                step["sequence_id"]
                == sequence_id
                and step["is_enabled"]
            )
        ]

    rows = (
        _client(settings)
        .table("outreach_sequence_steps")
        .select("*")
        .eq(
            "sequence_id",
            sequence_id,
        )
        .eq("is_enabled", True)
        .order(
            "step_number",
            desc=False,
        )
        .execute()
        .data
        or []
    )

    return rows


def _all_messages(
    settings: Settings,
    outreach_id: str,
    lead_id: str,
) -> list[dict[str, Any]]:
    if _uses_fallback(settings):
        state = (
            outreach_generation
            ._FALLBACK_STATE
            .get(lead_id)
        )

        if not state:
            return []

        messages = state.get(
            "messages"
        )

        if messages is None:
            latest = state.get(
                "latest_message"
            )

            messages = (
                [latest]
                if latest
                else []
            )

            state["messages"] = messages

        return messages

    return (
        _client(settings)
        .table("outreach_messages")
        .select("*")
        .eq(
            "lead_outreach_id",
            outreach_id,
        )
        .eq(
            "direction",
            "outbound",
        )
        .order(
            "step_number",
            desc=False,
        )
        .execute()
        .data
        or []
    )


def _render_template(
    template: str,
    lead: dict[str, Any],
) -> str:
    person_name = str(
        lead.get("person_name")
        or ""
    ).strip()

    first_name = (
        person_name.split()[0]
        if person_name
        else "there"
    )

    company_name = str(
        lead.get("company_name")
        or "your company"
    ).strip()

    replacements = {
        "first_name": first_name,
        "person_name": (
            person_name
            or first_name
        ),
        "company_name": company_name,
        "title": str(
            lead.get("title")
            or ""
        ).strip(),
    }

    rendered = template

    for key, value in replacements.items():
        rendered = rendered.replace(
            "{{" + key + "}}",
            value,
        )

    unresolved = re.findall(
        r"\{\{[^{}]+\}\}",
        rendered,
    )

    if unresolved:
        raise ValueError(
            "Sequence template contains unsupported placeholders: "
            + ", ".join(unresolved)
        )

    return rendered.strip()


def _event(
    settings: Settings,
    *,
    state: dict[str, Any],
    lead_id: str,
    actor_id: str,
    event_type: str,
    payload: dict[str, Any],
    message_id: str | None = None,
) -> None:
    outreach = state[
        "lead_outreach"
    ]

    if _uses_fallback(settings):
        raw_state = state.get(
            "_raw_state"
        )

        if raw_state is None:
            raw_state = (
                outreach_generation
                ._FALLBACK_STATE[
                    lead_id
                ]
            )

        outreach_delivery._fallback_event(
            raw_state,
            event_type=event_type,
            actor_id=actor_id,
            payload=payload,
        )

        return

    outreach_delivery._db_event(
        settings,
        lead_outreach_id=str(
            outreach["id"]
        ),
        message_id=str(
            message_id
            or outreach.get(
                "latest_message_id"
            )
            or state.get(
                "message",
                {},
            ).get("id")
            or ""
        ),
        lead_id=lead_id,
        actor_id=actor_id,
        event_type=event_type,
        payload=payload,
    )


def _context(
    settings: Settings,
    lead_id: str,
) -> dict[str, Any]:
    state = outreach_delivery._context(
        settings,
        lead_id,
    )

    if _uses_fallback(settings):
        state["_raw_state"] = (
            outreach_generation
            ._FALLBACK_STATE[
                lead_id
            ]
        )

    return state


def _next_step(
    settings: Settings,
    sequence_id: str,
    current_step_number: int,
) -> dict[str, Any] | None:
    steps = _sequence_steps(
        settings,
        sequence_id,
    )

    for step in steps:
        if int(
            step["step_number"]
        ) > current_step_number:
            return step

    return None


def _existing_step_message(
    settings: Settings,
    *,
    lead_id: str,
    outreach_id: str,
    step_number: int,
) -> dict[str, Any] | None:
    messages = _all_messages(
        settings,
        outreach_id,
        lead_id,
    )

    for message in messages:
        if (
            int(
                message.get(
                    "step_number"
                )
                or 0
            )
            == step_number
            and message.get(
                "direction"
            )
            == "outbound"
        ):
            return message

    return None


def _complete_sequence(
    settings: Settings,
    *,
    state: dict[str, Any],
    lead_id: str,
    actor_id: str,
    completed_step_number: int,
) -> dict[str, Any]:
    outreach = state[
        "lead_outreach"
    ]

    completed_at = _iso(
        _now_dt()
    )

    if _uses_fallback(settings):
        outreach["status"] = (
            "completed"
        )
        outreach[
            "current_step_number"
        ] = completed_step_number
        outreach["last_error"] = None
        outreach["updated_at"] = (
            completed_at
        )

    else:
        rows = (
            _client(settings)
            .table("lead_outreach")
            .update(
                {
                    "status": "completed",
                    "current_step_number": (
                        completed_step_number
                    ),
                    "last_error": None,
                    "updated_by": actor_id,
                }
            )
            .eq(
                "id",
                outreach["id"],
            )
            .execute()
            .data
            or []
        )

        if rows:
            state[
                "lead_outreach"
            ] = rows[0]

    _event(
        settings,
        state=state,
        lead_id=lead_id,
        actor_id=actor_id,
        event_type=(
            "sequence_completed"
        ),
        message_id=state.get(
            "message",
            {},
        ).get("id"),
        payload={
            "completed_at": (
                completed_at
            ),
            "completed_step_number": (
                completed_step_number
            ),
        },
    )

    return {
        "lead_id": lead_id,
        "status": "completed",
        "current_step_number": (
            completed_step_number
        ),
        "next_run_at": None,
    }


def _schedule_next(
    settings: Settings,
    *,
    state: dict[str, Any],
    lead_id: str,
    actor_id: str,
    after_step_number: int,
    base_time: datetime,
) -> dict[str, Any]:
    lead = state["lead"]
    outreach = state[
        "lead_outreach"
    ]

    sequence_id = str(
        outreach["sequence_id"]
    )

    next_step = _next_step(
        settings,
        sequence_id,
        after_step_number,
    )

    if next_step is None:
        return _complete_sequence(
            settings,
            state=state,
            lead_id=lead_id,
            actor_id=actor_id,
            completed_step_number=(
                after_step_number
            ),
        )

    step_number = int(
        next_step["step_number"]
    )

    existing = (
        _existing_step_message(
            settings,
            lead_id=lead_id,
            outreach_id=str(
                outreach["id"]
            ),
            step_number=step_number,
        )
    )

    if existing:
        existing_status = str(
            existing.get("status")
            or ""
        )

        if existing_status == "sent":
            existing_sent_at = (
                _parse_time(
                    existing.get(
                        "sent_at"
                    )
                )
                or base_time
            )

            return _schedule_next(
                settings,
                state={
                    **state,
                    "message": existing,
                },
                lead_id=lead_id,
                actor_id=actor_id,
                after_step_number=(
                    step_number
                ),
                base_time=(
                    existing_sent_at
                ),
            )

        scheduled_at = (
            existing.get(
                "scheduled_at"
            )
            or outreach.get(
                "next_run_at"
            )
        )

        return {
            "lead_id": lead_id,
            "status": (
                existing_status
                or "scheduled"
            ),
            "current_step_number": (
                step_number
            ),
            "next_run_at": (
                scheduled_at
            ),
            "message_id": existing[
                "id"
            ],
            "idempotent": True,
        }

    delay_days = int(
        next_step.get(
            "delay_days"
        )
        or 0
    )

    run_at_dt = (
        base_time
        + timedelta(
            days=delay_days,
        )
    )

    run_at = _iso(
        run_at_dt
    )

    subject = _render_template(
        str(
            next_step[
                "subject_template"
            ]
        ),
        lead,
    )

    body = _render_template(
        str(
            next_step[
                "message_template"
            ]
        ),
        lead,
    )

    recipient = (
        outreach_delivery
        ._normalize_recipient(
            str(
                lead.get("email")
                or ""
            ).strip()
        )
    )

    provider_name = (
        _provider_name(settings)
    )

    idempotency_key = (
        build_idempotency_key(
            lead_id=lead_id,
            sequence_id=sequence_id,
            step_number=step_number,
            recipient_email=recipient,
            provider_name=provider_name,
        )
    )

    now = _iso(
        _now_dt()
    )

    if _uses_fallback(settings):
        raw_state = state[
            "_raw_state"
        ]

        message = {
            "id": (
                "message-"
                + uuid4().hex
            ),
            "lead_outreach_id": (
                outreach["id"]
            ),
            "sequence_step_id": (
                next_step["id"]
            ),
            "step_number": (
                step_number
            ),
            "direction": "outbound",
            "status": "scheduled",
            "subject": subject,
            "body": body,
            "generation_provider": (
                "sequence_template"
            ),
            "generation_model": None,
            "provider_message_id": (
                None
            ),
            "idempotency_key": (
                idempotency_key
            ),
            "error_message": None,
            "provider_response": {
                "evidence_refs": [],
                "grounding_status": (
                    "sequence_template"
                ),
                "grounding_warnings": [],
                "provider": (
                    "sequence_template"
                ),
                "model": None,
                "generated_at": now,
            },
            "generated_at": now,
            "approved_at": None,
            "approved_by": None,
            "scheduled_at": (
                run_at
            ),
            "sent_at": None,
            "replied_at": None,
            "created_by": (
                actor_id
            ),
            "updated_by": (
                actor_id
            ),
            "created_at": now,
            "updated_at": now,
        }

        messages = raw_state.get(
            "messages"
        )

        if messages is None:
            previous = raw_state.get(
                "latest_message"
            )

            messages = (
                [previous]
                if previous
                else []
            )

            raw_state[
                "messages"
            ] = messages

        messages.append(message)

        raw_state[
            "latest_message"
        ] = message

        outreach[
            "latest_message_id"
        ] = message["id"]

        outreach[
            "current_step_number"
        ] = step_number

        outreach["status"] = (
            "scheduled"
        )

        outreach["next_run_at"] = (
            run_at
        )

        outreach["last_error"] = None
        outreach["updated_at"] = now

        state["message"] = message

    else:
        client = _client(settings)

        rows = (
            client
            .table(
                "outreach_messages"
            )
            .insert(
                {
                    "lead_outreach_id": (
                        outreach["id"]
                    ),
                    "sequence_step_id": (
                        next_step["id"]
                    ),
                    "step_number": (
                        step_number
                    ),
                    "direction": (
                        "outbound"
                    ),
                    "status": (
                        "scheduled"
                    ),
                    "subject": subject,
                    "body": body,
                    "generation_provider": (
                        "sequence_template"
                    ),
                    "generation_model": (
                        None
                    ),
                    "idempotency_key": (
                        idempotency_key
                    ),
                    "provider_response": {
                        "evidence_refs": [],
                        "grounding_status": (
                            "sequence_template"
                        ),
                        "grounding_warnings": [],
                        "provider": (
                            "sequence_template"
                        ),
                        "model": None,
                        "generated_at": now,
                    },
                    "generated_at": now,
                    "scheduled_at": (
                        run_at
                    ),
                    "created_by": (
                        actor_id
                    ),
                    "updated_by": (
                        actor_id
                    ),
                }
            )
            .execute()
            .data
            or []
        )

        if not rows:
            raise RuntimeError(
                "Unable to create scheduled follow-up"
            )

        message = rows[0]

        outreach_rows = (
            client
            .table(
                "lead_outreach"
            )
            .update(
                {
                    "status": (
                        "scheduled"
                    ),
                    "current_step_number": (
                        step_number
                    ),
                    "next_run_at": (
                        run_at
                    ),
                    "latest_message_id": (
                        message["id"]
                    ),
                    "last_error": None,
                    "updated_by": (
                        actor_id
                    ),
                }
            )
            .eq(
                "id",
                outreach["id"],
            )
            .execute()
            .data
            or []
        )

        if outreach_rows:
            state[
                "lead_outreach"
            ] = outreach_rows[0]

        state["message"] = message

    _event(
        settings,
        state=state,
        lead_id=lead_id,
        actor_id=actor_id,
        event_type=(
            "followup_scheduled"
        ),
        message_id=state[
            "message"
        ]["id"],
        payload={
            "step_number": (
                step_number
            ),
            "delay_days": (
                delay_days
            ),
            "next_run_at": (
                run_at
            ),
            "idempotency_key": (
                idempotency_key
            ),
        },
    )

    return {
        "lead_id": lead_id,
        "status": "scheduled",
        "current_step_number": (
            step_number
        ),
        "next_run_at": run_at,
        "message_id": state[
            "message"
        ]["id"],
        "idempotent": False,
    }


def schedule_next_followup(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> dict[str, Any]:
    state = _context(
        settings,
        lead_id,
    )

    lead = state["lead"]
    outreach = state[
        "lead_outreach"
    ]
    message = state["message"]

    outreach_delivery._assert_access(
        lead,
        actor_id,
        role,
    )

    if outreach.get(
        "status"
    ) == "completed":
        return {
            "lead_id": lead_id,
            "status": (
                "completed"
            ),
            "current_step_number": (
                outreach.get(
                    "current_step_number"
                )
            ),
            "next_run_at": None,
            "idempotent": True,
        }

    if message.get(
        "status"
    ) == "scheduled":
        return {
            "lead_id": lead_id,
            "status": (
                "scheduled"
            ),
            "current_step_number": (
                message.get(
                    "step_number"
                )
            ),
            "next_run_at": (
                message.get(
                    "scheduled_at"
                )
                or outreach.get(
                    "next_run_at"
                )
            ),
            "message_id": (
                message["id"]
            ),
            "idempotent": True,
        }

    if message.get(
        "status"
    ) != "sent":
        raise ValueError(
            "The current sequence step must be sent before scheduling the next follow-up"
        )

    sent_at = (
        _parse_time(
            message.get(
                "sent_at"
            )
        )
        or _now_dt()
    )

    return _schedule_next(
        settings,
        state=state,
        lead_id=lead_id,
        actor_id=actor_id,
        after_step_number=int(
            message.get(
                "step_number"
            )
            or outreach.get(
                "current_step_number"
            )
            or 1
        ),
        base_time=sent_at,
    )


def pause_sequence(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    if not (
        can_manage_outbound_sequences(
            role
        )
    ):
        raise PermissionError(
            "Admin or manager role required to pause sequences"
        )

    reason = reason.strip()

    if not reason:
        raise ValueError(
            "A pause reason is required"
        )

    state = _context(
        settings,
        lead_id,
    )

    outreach = state[
        "lead_outreach"
    ]

    if outreach.get(
        "status"
    ) == "completed":
        raise ValueError(
            "Completed sequences cannot be paused"
        )

    paused_at = _iso(
        _now_dt()
    )

    if _uses_fallback(settings):
        outreach["status"] = (
            "paused"
        )
        outreach[
            "paused_reason"
        ] = reason
        outreach["updated_at"] = (
            paused_at
        )

    else:
        rows = (
            _client(settings)
            .table("lead_outreach")
            .update(
                {
                    "status": "paused",
                    "paused_reason": reason,
                    "updated_by": (
                        actor_id
                    ),
                }
            )
            .eq(
                "id",
                outreach["id"],
            )
            .execute()
            .data
            or []
        )

        if rows:
            state[
                "lead_outreach"
            ] = rows[0]

    _event(
        settings,
        state=state,
        lead_id=lead_id,
        actor_id=actor_id,
        event_type=(
            "sequence_paused"
        ),
        message_id=state[
            "message"
        ]["id"],
        payload={
            "reason": reason,
            "paused_at": (
                paused_at
            ),
        },
    )

    return {
        "lead_id": lead_id,
        "status": "paused",
        "paused_reason": reason,
        "next_run_at": (
            outreach.get(
                "next_run_at"
            )
        ),
    }


def resume_sequence(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> dict[str, Any]:
    if not (
        can_manage_outbound_sequences(
            role
        )
    ):
        raise PermissionError(
            "Admin or manager role required to resume sequences"
        )

    state = _context(
        settings,
        lead_id,
    )

    outreach = state[
        "lead_outreach"
    ]
    message = state[
        "message"
    ]

    if outreach.get(
        "status"
    ) != "paused":
        raise ValueError(
            "Only a paused sequence can be resumed"
        )

    resumed_at = _iso(
        _now_dt()
    )

    if message.get(
        "status"
    ) == "scheduled":
        next_run_at = (
            message.get(
                "scheduled_at"
            )
            or outreach.get(
                "next_run_at"
            )
            or resumed_at
        )

        if _uses_fallback(settings):
            outreach[
                "status"
            ] = "scheduled"
            outreach[
                "paused_reason"
            ] = None
            outreach[
                "next_run_at"
            ] = next_run_at
            outreach[
                "updated_at"
            ] = resumed_at

        else:
            rows = (
                _client(settings)
                .table(
                    "lead_outreach"
                )
                .update(
                    {
                        "status": (
                            "scheduled"
                        ),
                        "paused_reason": (
                            None
                        ),
                        "next_run_at": (
                            next_run_at
                        ),
                        "updated_by": (
                            actor_id
                        ),
                    }
                )
                .eq(
                    "id",
                    outreach["id"],
                )
                .execute()
                .data
                or []
            )

            if rows:
                state[
                    "lead_outreach"
                ] = rows[0]

        _event(
            settings,
            state=state,
            lead_id=lead_id,
            actor_id=actor_id,
            event_type=(
                "sequence_resumed"
            ),
            message_id=(
                message["id"]
            ),
            payload={
                "resumed_at": (
                    resumed_at
                ),
                "next_run_at": (
                    next_run_at
                ),
            },
        )

        return {
            "lead_id": lead_id,
            "status": "scheduled",
            "next_run_at": (
                next_run_at
            ),
            "current_step_number": (
                outreach.get(
                    "current_step_number"
                )
            ),
        }

    if message.get(
        "status"
    ) == "sent":
        if _uses_fallback(settings):
            outreach[
                "paused_reason"
            ] = None
            outreach[
                "status"
            ] = "sent"
        else:
            (
                _client(settings)
                .table(
                    "lead_outreach"
                )
                .update(
                    {
                        "status": "sent",
                        "paused_reason": (
                            None
                        ),
                        "updated_by": (
                            actor_id
                        ),
                    }
                )
                .eq(
                    "id",
                    outreach["id"],
                )
                .execute()
            )

        return schedule_next_followup(
            settings,
            actor_id,
            role,
            lead_id,
        )

    raise ValueError(
        "Paused sequence does not have a resumable message"
    )


def _block_sequence(
    settings: Settings,
    *,
    state: dict[str, Any],
    lead_id: str,
    actor_id: str,
    reason: str,
) -> dict[str, Any]:
    outreach = state[
        "lead_outreach"
    ]

    now = _iso(
        _now_dt()
    )

    if _uses_fallback(settings):
        outreach["status"] = (
            "paused"
        )
        outreach[
            "paused_reason"
        ] = reason
        outreach["last_error"] = (
            reason
        )
        outreach["updated_at"] = now

    else:
        (
            _client(settings)
            .table("lead_outreach")
            .update(
                {
                    "status": "paused",
                    "paused_reason": (
                        reason
                    ),
                    "last_error": reason,
                    "updated_by": (
                        actor_id
                    ),
                }
            )
            .eq(
                "id",
                outreach["id"],
            )
            .execute()
        )

    _event(
        settings,
        state=state,
        lead_id=lead_id,
        actor_id=actor_id,
        event_type=(
            "sequence_blocked"
        ),
        message_id=state[
            "message"
        ]["id"],
        payload={
            "reason": reason,
            "blocked_at": now,
        },
    )

    return {
        "lead_id": lead_id,
        "status": "paused",
        "reason": reason,
    }


def _claim_scheduled_message(
    settings: Settings,
    *,
    message: dict[str, Any],
    actor_id: str,
) -> bool:
    """Atomically claim a scheduled message before provider delivery."""

    if message.get("status") != "scheduled":
        return False

    if _uses_fallback(settings):
        message["status"] = "sending"
        message["updated_at"] = _iso(
            _now_dt()
        )
        return True

    rows = (
        _client(settings)
        .table("outreach_messages")
        .update(
            {
                "status": "sending",
                "updated_by": actor_id,
            }
        )
        .eq(
            "id",
            message["id"],
        )
        .eq(
            "status",
            "scheduled",
        )
        .execute()
        .data
        or []
    )

    if not rows:
        return False

    message.update(rows[0])
    return True


def _send_due_for_lead(
    settings: Settings,
    *,
    actor_id: str,
    role: str,
    lead_id: str,
    now: datetime,
) -> dict[str, Any]:
    state = _context(
        settings,
        lead_id,
    )

    lead = state["lead"]
    outreach = state[
        "lead_outreach"
    ]
    message = state[
        "message"
    ]

    if outreach.get(
        "status"
    ) != "scheduled":
        return {
            "lead_id": lead_id,
            "status": "skipped",
            "reason": (
                "sequence_not_scheduled"
            ),
        }

    if message.get(
        "status"
    ) == "sent":
        return schedule_next_followup(
            settings,
            actor_id,
            role,
            lead_id,
        )

    if message.get(
        "status"
    ) != "scheduled":
        return {
            "lead_id": lead_id,
            "status": "skipped",
            "reason": (
                "message_not_scheduled"
            ),
        }

    due_at = (
        _parse_time(
            message.get(
                "scheduled_at"
            )
        )
        or _parse_time(
            outreach.get(
                "next_run_at"
            )
        )
    )

    if (
        due_at is not None
        and due_at > now
    ):
        return {
            "lead_id": lead_id,
            "status": "not_due",
            "next_run_at": (
                _iso(due_at)
            ),
        }

    try:
        recipient = (
            outreach_delivery
            ._assert_lead_send_eligible(
                settings,
                lead,
                actor_id,
                role,
            )
        )
    except (
        PermissionError,
        ValueError,
    ) as exc:
        return _block_sequence(
            settings,
            state=state,
            lead_id=lead_id,
            actor_id=actor_id,
            reason=str(exc),
        )

    provider_name = (
        _provider_name(settings)
    )

    step_number = int(
        message.get(
            "step_number"
        )
        or outreach.get(
            "current_step_number"
        )
        or 1
    )

    idempotency_key = (
        str(
            message.get(
                "idempotency_key"
            )
            or ""
        ).strip()
        or build_idempotency_key(
            lead_id=lead_id,
            sequence_id=str(
                outreach[
                    "sequence_id"
                ]
            ),
            step_number=(
                step_number
            ),
            recipient_email=(
                recipient
            ),
            provider_name=(
                provider_name
            ),
        )
    )

    subject = str(
        message.get("subject")
        or ""
    ).strip()

    body = str(
        message.get("body")
        or ""
    ).strip()

    if not subject or not body:
        return _block_sequence(
            settings,
            state=state,
            lead_id=lead_id,
            actor_id=actor_id,
            reason=(
                "Scheduled follow-up is missing subject or body"
            ),
        )

    request = OutboundEmailRequest(
        lead_id=lead_id,
        lead_outreach_id=str(
            outreach["id"]
        ),
        sequence_id=str(
            outreach[
                "sequence_id"
            ]
        ),
        step_number=step_number,
        sender_email=(
            settings.gmail_sender_email
            or "outreach@datamart.test"
        ),
        recipient_email=recipient,
        subject=subject,
        body=body,
        idempotency_key=(
            idempotency_key
        ),
        provider_name=provider_name,
        metadata={
            "message_id": (
                message["id"]
            ),
            "automatic_followup": (
                True
            ),
        },
    )

    claimed = _claim_scheduled_message(
        settings,
        message=message,
        actor_id=actor_id,
    )

    if not claimed:
        refreshed = _existing_step_message(
            settings,
            lead_id=lead_id,
            outreach_id=str(
                outreach["id"]
            ),
            step_number=step_number,
        )

        refreshed_status = str(
            (refreshed or {}).get("status")
            or ""
        )

        if refreshed_status == "sent":
            return {
                "lead_id": lead_id,
                "status": "sent",
                "step_number": step_number,
                "provider_message_id": (
                    (refreshed or {}).get(
                        "provider_message_id"
                    )
                ),
                "sent_at": (
                    (refreshed or {}).get(
                        "sent_at"
                    )
                ),
                "idempotent": True,
            }

        return {
            "lead_id": lead_id,
            "status": "skipped",
            "step_number": step_number,
            "reason": (
                "message_already_claimed"
                if refreshed_status == "sending"
                else "message_not_scheduled"
            ),
        }

    attempted_at = _iso(
        _now_dt()
    )

    _event(
        settings,
        state=state,
        lead_id=lead_id,
        actor_id=actor_id,
        event_type=(
            "followup_send_attempted"
        ),
        message_id=message[
            "id"
        ],
        payload={
            "step_number": (
                step_number
            ),
            "attempted_at": (
                attempted_at
            ),
            "provider": (
                provider_name
            ),
            "idempotency_key": (
                idempotency_key
            ),
        },
    )

    provider = (
        outreach_delivery
        ._provider(settings)
    )

    try:
        result = provider.send(
            request
        )

        if str(
            result.status
        ).casefold() != "sent":
            raise RuntimeError(
                "Outbound provider did not confirm successful delivery"
            )

    except Exception as exc:
        error_message = (
            str(exc).strip()
            or "Automated follow-up delivery failed"
        )

        if _uses_fallback(settings):
            message["status"] = (
                "failed"
            )
            message[
                "error_message"
            ] = error_message
            message[
                "idempotency_key"
            ] = idempotency_key
            message[
                "updated_at"
            ] = _iso(
                _now_dt()
            )

            outreach["status"] = (
                "failed"
            )
            outreach[
                "last_error"
            ] = error_message

        else:
            client = _client(
                settings
            )

            (
                client
                .table(
                    "outreach_messages"
                )
                .update(
                    {
                        "status": "failed",
                        "error_message": (
                            error_message
                        ),
                        "idempotency_key": (
                            idempotency_key
                        ),
                        "updated_by": (
                            actor_id
                        ),
                    }
                )
                .eq(
                    "id",
                    message["id"],
                )
                .eq(
                    "status",
                    "sending",
                )
                .execute()
            )

            (
                client
                .table(
                    "lead_outreach"
                )
                .update(
                    {
                        "status": "failed",
                        "last_error": (
                            error_message
                        ),
                        "updated_by": (
                            actor_id
                        ),
                    }
                )
                .eq(
                    "id",
                    outreach["id"],
                )
                .execute()
            )

        _event(
            settings,
            state=state,
            lead_id=lead_id,
            actor_id=actor_id,
            event_type=(
                "followup_send_failed"
            ),
            message_id=message[
                "id"
            ],
            payload={
                "step_number": (
                    step_number
                ),
                "provider": (
                    provider_name
                ),
                "error": (
                    error_message
                ),
                "idempotency_key": (
                    idempotency_key
                ),
            },
        )

        return {
            "lead_id": lead_id,
            "status": "failed",
            "step_number": (
                step_number
            ),
            "error": (
                error_message
            ),
        }

    sent_at = _iso(
        result.sent_at
    )

    if _uses_fallback(settings):
        message["status"] = "sent"
        message[
            "provider_message_id"
        ] = result.provider_message_id
        message["sent_at"] = (
            sent_at
        )
        message[
            "error_message"
        ] = None
        message[
            "idempotency_key"
        ] = idempotency_key
        message[
            "updated_at"
        ] = sent_at

        outreach["status"] = (
            "sent"
        )
        outreach[
            "current_step_number"
        ] = step_number
        outreach["last_error"] = (
            None
        )
        outreach["updated_at"] = (
            sent_at
        )

    else:
        client = _client(
            settings
        )

        rows = (
            client
            .table(
                "outreach_messages"
            )
            .update(
                {
                    "status": "sent",
                    "provider_message_id": (
                        result.provider_message_id
                    ),
                    "sent_at": (
                        sent_at
                    ),
                    "error_message": (
                        None
                    ),
                    "idempotency_key": (
                        idempotency_key
                    ),
                    "updated_by": (
                        actor_id
                    ),
                }
            )
            .eq(
                "id",
                message["id"],
            )
            .eq(
                "status",
                "sending",
            )
            .execute()
            .data
            or []
        )

        if not rows:
            refreshed = (
                _existing_step_message(
                    settings,
                    lead_id=lead_id,
                    outreach_id=str(
                        outreach["id"]
                    ),
                    step_number=(
                        step_number
                    ),
                )
            )

            if (
                refreshed
                and refreshed.get(
                    "status"
                )
                == "sent"
            ):
                return {
                    "lead_id": (
                        lead_id
                    ),
                    "status": "sent",
                    "step_number": (
                        step_number
                    ),
                    "provider_message_id": (
                        refreshed.get(
                            "provider_message_id"
                        )
                    ),
                    "sent_at": (
                        refreshed.get(
                            "sent_at"
                        )
                    ),
                    "idempotent": True,
                }

            raise RuntimeError(
                "Unable to persist automated follow-up delivery"
            )

        (
            client
            .table(
                "lead_outreach"
            )
            .update(
                {
                    "status": "sent",
                    "current_step_number": (
                        step_number
                    ),
                    "last_error": None,
                    "updated_by": (
                        actor_id
                    ),
                }
            )
            .eq(
                "id",
                outreach["id"],
            )
            .execute()
        )

    _event(
        settings,
        state=state,
        lead_id=lead_id,
        actor_id=actor_id,
        event_type=(
            "followup_sent"
        ),
        message_id=message["id"],
        payload={
            "step_number": (
                step_number
            ),
            "provider": (
                result.provider_name
            ),
            "provider_message_id": (
                result.provider_message_id
            ),
            "sent_at": sent_at,
            "idempotency_key": (
                idempotency_key
            ),
        },
    )

    refreshed_state = _context(
        settings,
        lead_id,
    )

    next_result = _schedule_next(
        settings,
        state=refreshed_state,
        lead_id=lead_id,
        actor_id=actor_id,
        after_step_number=(
            step_number
        ),
        base_time=(
            _parse_time(sent_at)
            or now
        ),
    )

    return {
        "lead_id": lead_id,
        "status": "sent",
        "step_number": (
            step_number
        ),
        "provider": (
            result.provider_name
        ),
        "provider_message_id": (
            result.provider_message_id
        ),
        "sent_at": sent_at,
        "idempotent": False,
        "next": next_result,
    }


def run_due_followups(
    settings: Settings,
    actor_id: str,
    role: str,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if not (
        can_manage_outbound_sequences(
            role
        )
    ):
        raise PermissionError(
            "Admin or manager role required to run scheduled follow-ups"
        )

    if limit < 1 or limit > 100:
        raise ValueError(
            "limit must be between 1 and 100"
        )

    effective_now = (
        now.astimezone(UTC)
        if now
        else _now_dt()
    )

    lead_ids: list[str] = []

    if _uses_fallback(settings):
        for (
            lead_id,
            state,
        ) in (
            outreach_generation
            ._FALLBACK_STATE
            .items()
        ):
            outreach = state.get(
                "lead_outreach"
            ) or {}

            if outreach.get(
                "status"
            ) != "scheduled":
                continue

            next_run_at = (
                _parse_time(
                    outreach.get(
                        "next_run_at"
                    )
                )
            )

            if (
                next_run_at
                and next_run_at
                > effective_now
            ):
                continue

            lead_ids.append(
                lead_id
            )

            if (
                len(lead_ids)
                >= limit
            ):
                break

    else:
        rows = (
            _client(settings)
            .table("lead_outreach")
            .select(
                "lead_id,next_run_at"
            )
            .eq(
                "status",
                "scheduled",
            )
            .lte(
                "next_run_at",
                _iso(
                    effective_now
                ),
            )
            .order(
                "next_run_at",
                desc=False,
            )
            .limit(limit)
            .execute()
            .data
            or []
        )

        lead_ids = [
            str(row["lead_id"])
            for row in rows
        ]

    results: list[
        dict[str, Any]
    ] = []

    for lead_id in lead_ids:
        try:
            result = (
                _send_due_for_lead(
                    settings,
                    actor_id=actor_id,
                    role=role,
                    lead_id=lead_id,
                    now=effective_now,
                )
            )
        except Exception as exc:
            result = {
                "lead_id": lead_id,
                "status": "failed",
                "error": (
                    str(exc)
                    or "Unexpected sequence execution failure"
                ),
            }

        results.append(result)

    return {
        "checked_at": _iso(
            effective_now
        ),
        "processed": len(
            results
        ),
        "results": results,
    }


def get_sequence_state(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> dict[str, Any]:
    state = _context(
        settings,
        lead_id,
    )

    lead = state["lead"]
    outreach = state[
        "lead_outreach"
    ]

    outreach_delivery._assert_access(
        lead,
        actor_id,
        role,
    )

    messages = _all_messages(
        settings,
        str(
            outreach["id"]
        ),
        lead_id,
    )

    steps = _sequence_steps(
        settings,
        str(
            outreach["sequence_id"]
        ),
    )

    history = [
        {
            "id": message[
                "id"
            ],
            "step_number": (
                message.get(
                    "step_number"
                )
            ),
            "status": (
                message.get(
                    "status"
                )
            ),
            "subject": (
                message.get(
                    "subject"
                )
            ),
            "scheduled_at": (
                message.get(
                    "scheduled_at"
                )
            ),
            "sent_at": (
                message.get(
                    "sent_at"
                )
            ),
            "provider_message_id": (
                message.get(
                    "provider_message_id"
                )
            ),
            "error_message": (
                message.get(
                    "error_message"
                )
            ),
        }
        for message in messages
    ]

    return {
        "lead_id": lead_id,
        "sequence_id": (
            outreach[
                "sequence_id"
            ]
        ),
        "status": outreach.get(
            "status"
        ),
        "current_step_number": (
            outreach.get(
                "current_step_number"
            )
        ),
        "next_run_at": (
            outreach.get(
                "next_run_at"
            )
            if outreach.get(
                "status"
            )
            == "scheduled"
            else None
        ),
        "paused_reason": (
            outreach.get(
                "paused_reason"
            )
        ),
        "last_error": (
            outreach.get(
                "last_error"
            )
        ),
        "total_steps": len(
            steps
        ),
        "messages": history,
    }
