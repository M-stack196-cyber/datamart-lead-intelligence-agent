from app.integrations.outbound import (
    CrmHandoffRequest,
    InboundReplyRequest,
    MockCrmProvider,
    MockInboundReplyProvider,
    MockOutboundEmailProvider,
    OutboundEmailRequest,
)
from app.schemas.outbound import (
    CrmSyncMetadata,
    LeadOutreach,
    OutreachMessage,
    OutreachSequence,
    OutreachSequenceStep,
    OutboundDirection,
    OutboundLifecycleStatus,
    SuppressionEntry,
    SuppressionKind,
)
from app.services.outbound import (
    build_idempotency_key,
    can_manage_crm_sync,
    can_manage_outbound_sequences,
    can_manage_outbound_suppression,
    find_suppression_entry,
    is_suppressed,
    ordered_sequence_steps,
)


def test_sequence_model_sorts_steps_and_rejects_duplicates() -> None:
    sequence = OutreachSequence(
        id="sequence-1",
        external_id="datamart-outbound-sequence-v1",
        name="Datamart Outreach Sequence",
        steps=[
            OutreachSequenceStep(
                id="step-3",
                sequence_id="sequence-1",
                step_number=3,
                delay_days=7,
                subject_template="Follow-up",
                message_template="Follow-up body",
            ),
            OutreachSequenceStep(
                id="step-1",
                sequence_id="sequence-1",
                step_number=1,
                delay_days=0,
                subject_template="Intro",
                message_template="Intro body",
            ),
        ],
    )

    assert [step.step_number for step in sequence.steps] == [1, 3]

    duplicate_steps = [
        OutreachSequenceStep(
            id="step-a",
            sequence_id="sequence-1",
            step_number=1,
            delay_days=0,
            subject_template="Intro",
            message_template="Intro body",
        ),
        OutreachSequenceStep(
            id="step-b",
            sequence_id="sequence-1",
            step_number=1,
            delay_days=3,
            subject_template="Duplicate",
            message_template="Duplicate body",
        ),
    ]

    try:
        OutreachSequence(
            id="sequence-1",
            external_id="datamart-outbound-sequence-v1",
            name="Datamart Outreach Sequence",
            steps=duplicate_steps,
        )
    except ValueError as exc:
        assert "unique" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("duplicate steps must be rejected")


def test_message_lifecycle_validates_idempotency_and_direction() -> None:
    message = OutreachMessage(
        id="message-1",
        lead_outreach_id="outreach-1",
        sequence_step_id="step-1",
        step_number=1,
        direction=OutboundDirection.OUTBOUND,
        status=OutboundLifecycleStatus.DRAFT,
        subject="Intro",
        body="Approved body",
    )
    assert message.status == OutboundLifecycleStatus.DRAFT

    try:
        OutreachMessage(
            id="message-2",
            lead_outreach_id="outreach-1",
            sequence_step_id="step-1",
            step_number=1,
            direction=OutboundDirection.OUTBOUND,
            status=OutboundLifecycleStatus.SCHEDULED,
            subject="Intro",
            body="Approved body",
        )
    except ValueError as exc:
        assert "idempotency_key" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("scheduled messages require idempotency")

    replied = OutreachMessage(
        id="message-3",
        lead_outreach_id="outreach-1",
        direction=OutboundDirection.INBOUND,
        status=OutboundLifecycleStatus.REPLIED,
        body="Thanks, send more info",
        idempotency_key="reply-1",
    )
    assert replied.direction == OutboundDirection.INBOUND


def test_suppression_lookup_matches_normalized_email() -> None:
    entry = SuppressionEntry(
        id="suppression-1",
        email=" Sales@Example.com ",
        suppression_kind=SuppressionKind.MANUAL,
        reason="Requested by sales ops",
    )

    assert entry.normalized_email == "sales@example.com"
    assert is_suppressed("sales@example.com", [entry])
    assert find_suppression_entry("SALES@example.com", [entry]) == entry


def test_idempotency_key_is_deterministic_and_step_specific() -> None:
    key_one = build_idempotency_key(
        lead_id="lead-1",
        sequence_id="sequence-1",
        step_number=1,
        recipient_email="lead@example.com",
    )
    key_two = build_idempotency_key(
        lead_id="lead-1",
        sequence_id="sequence-1",
        step_number=1,
        recipient_email="LEAD@example.com",
    )
    key_three = build_idempotency_key(
        lead_id="lead-1",
        sequence_id="sequence-1",
        step_number=2,
        recipient_email="lead@example.com",
    )

    assert key_one == key_two
    assert key_one != key_three


def test_role_helpers_cover_manager_and_admin_boundaries() -> None:
    assert can_manage_outbound_sequences("admin") is True
    assert can_manage_outbound_sequences("manager") is True
    assert can_manage_outbound_sequences("sales") is False
    assert can_manage_outbound_suppression("admin") is True
    assert can_manage_outbound_suppression("manager") is False
    assert can_manage_crm_sync("manager") is True


def test_mock_outbound_providers_record_requests() -> None:
    email_provider = MockOutboundEmailProvider()
    reply_provider = MockInboundReplyProvider()
    crm_provider = MockCrmProvider()

    email_result = email_provider.send(
        OutboundEmailRequest(
            lead_id="lead-1",
            lead_outreach_id="outreach-1",
            sequence_id="sequence-1",
            step_number=1,
            sender_email="sales@datamart.test",
            recipient_email="lead@example.com",
            subject="Intro",
            body="Approved body",
            idempotency_key="idempotent-1",
        )
    )
    reply_result = reply_provider.ingest_reply(
        InboundReplyRequest(
            provider_name="mock-reply",
            lead_id="lead-1",
            lead_outreach_id="outreach-1",
            thread_id=None,
            provider_message_id=None,
            from_email="lead@example.com",
            to_email="sales@datamart.test",
            subject="Re: Intro",
            body="Thanks",
            received_at=email_result.sent_at,
        )
    )
    crm_result = crm_provider.push(
        CrmHandoffRequest(
            lead_id="lead-1",
            lead_outreach_id="outreach-1",
            provider_key="mock-crm",
            external_crm_id=None,
            mapping={"lead_id": "lead-1"},
            idempotency_key="crm-1",
        )
    )

    assert email_provider.sent_requests[0].recipient_email == "lead@example.com"
    assert reply_provider.captured_requests[0].lead_id == "lead-1"
    assert crm_provider.pushed_requests[0].provider_key == "mock-crm"
    assert email_result.status == "sent"
    assert reply_result.status == "stored"
    assert crm_result.sync_status == "synced"


def test_crm_metadata_and_lead_outreach_models_validate_minimal_state() -> None:
    crm_state = CrmSyncMetadata(
        id="crm-state-1",
        lead_id="lead-1",
        provider_key="mock-crm",
    )
    lead_outreach = LeadOutreach(
        id="outreach-1",
        lead_id="lead-1",
        sequence_id="sequence-1",
        status=OutboundLifecycleStatus.DRAFT,
        current_step_number=1,
    )

    assert crm_state.sync_status.value == "pending"
    assert lead_outreach.status == OutboundLifecycleStatus.DRAFT
