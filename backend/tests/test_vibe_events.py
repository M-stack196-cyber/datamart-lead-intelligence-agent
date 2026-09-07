from unittest.mock import Mock, patch

from app.integrations.vibe.events import (
    VibeEventsClient,
)


@patch(
    "app.integrations.vibe.events.httpx.post"
)
def test_fetch_business_events(mock_post):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "output_events": [
            {
                "business_id": "business-1",
                "event_id": "evt-1",
                "event_name": "new_funding_round",
                "event_time": "2026-09-03T12:00:00Z",
                "data": {
                    "source_url": (
                        "https://example.com/"
                        "funding"
                    ),
                    "description": (
                        "Company announced "
                        "a new funding round."
                    ),
                },
            }
        ]
    }

    mock_post.return_value = response

    client = VibeEventsClient(
        "test-key"
    )

    events = client.fetch_business_events(
        ["business-1"],
        event_types=["new_funding_round"],
        timestamp_from="2026-08-01",
    )

    assert len(events) == 1

    event = events[0]

    assert event.business_id == "business-1"
    assert event.event_id == "evt-1"
    assert (
        event.event_type
        == "new_funding_round"
    )
    assert (
        event.occurred_at
        == "2026-09-03T12:00:00Z"
    )
    assert (
        event.source_url
        == "https://example.com/funding"
    )

    mock_post.assert_called_once()


def test_business_event_limit():
    client = VibeEventsClient(
        "test-key"
    )

    ids = [
        f"id-{index}"
        for index in range(41)
    ]

    try:
        client.fetch_business_events(ids)
    except ValueError as exc:
        assert "40 business IDs" in str(exc)
    else:
        raise AssertionError(
            "Expected ValueError"
        )
