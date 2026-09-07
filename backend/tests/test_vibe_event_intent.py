from app.integrations.vibe.events import VibeBusinessEvent
from app.intent import IntentEngine
from app.services.vibe_event_intent import (
    business_event_to_evidence,
    business_events_to_evidence,
)


def funding_event():
    return VibeBusinessEvent(
        business_id="business-1",
        event_id="evt-funding-1",
        event_type="new_funding_round",
        title="Company raises new funding round",
        occurred_at="2026-09-03T12:00:00Z",
        source_url="https://example.com/funding",
        excerpt="The company announced a new funding round.",
        raw_data={},
    )


def test_funding_event_becomes_intent_evidence():
    item = business_event_to_evidence(
        funding_event()
    )

    assert item is not None
    assert item["intent_signal"] == "funding"
    assert item["intent_score_delta"] == 20
    assert item["activity_at"] == (
        "2026-09-03T12:00:00Z"
    )
    assert "intent" in item["supports_fields"]


def test_event_without_source_is_not_stored():
    event = VibeBusinessEvent(
        business_id="business-1",
        event_id="evt-2",
        event_type="hiring",
        title="Hiring update",
        occurred_at=None,
        source_url=None,
        excerpt=None,
        raw_data={},
    )

    assert business_event_to_evidence(
        event
    ) is None


def test_duplicate_event_urls_are_removed():
    event = funding_event()

    result = business_events_to_evidence(
        [event, event]
    )

    assert len(result) == 1


def test_business_event_affects_intent():
    evidence = business_events_to_evidence(
        [funding_event()]
    )

    result = IntentEngine.score(
        {
            "company_name": "Cloud Labs",
            "title": "CEO",
        },
        evidence,
    )

    assert result.score > 0

    assert any(
        "funding" in reason.casefold()
        for reason in result.reasons
    )

    assert (
        "Source-backed activity provides "
        "direct intent evidence"
        in result.reasons
    )
