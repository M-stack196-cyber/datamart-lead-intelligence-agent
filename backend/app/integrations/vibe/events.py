from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class VibeBusinessEvent:
    business_id: str | None
    event_id: str | None
    event_type: str
    title: str
    occurred_at: str | None
    source_url: str | None
    excerpt: str | None
    raw_data: dict[str, Any]


class VibeEventsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.explorium.ai",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "API_KEY": self.api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _source_url(
        data: dict[str, Any],
    ) -> str | None:
        for key in (
            "source_url",
            "source",
            "url",
            "article_url",
        ):
            value = data.get(key)

            if (
                isinstance(value, str)
                and value.strip()
            ):
                return value.strip()

        return None

    @staticmethod
    def _title(
        event_type: str,
        event: dict[str, Any],
    ) -> str:
        for key in (
            "title",
            "event_name",
            "name",
        ):
            value = event.get(key)

            if (
                isinstance(value, str)
                and value.strip()
            ):
                return value.strip()

        return event_type.replace(
            "_",
            " ",
        ).title()

    def fetch_business_events(
        self,
        business_ids: list[str],
        *,
        event_types: list[str] | None = None,
        timestamp_from: str | None = None,
    ) -> list[VibeBusinessEvent]:
        ids = [
            item.strip()
            for item in business_ids
            if isinstance(item, str)
            and item.strip()
        ]

        if not ids:
            return []

        if len(ids) > 40:
            raise ValueError(
                "A maximum of 40 business IDs "
                "may be requested per call"
            )

        payload: dict[str, Any] = {
            "business_ids": ids,
        }

        if event_types:
            payload["event_types"] = (
                event_types
            )

        if timestamp_from:
            payload["timestamp_from"] = (
                timestamp_from
            )

        response = httpx.post(
            (
                f"{self.base_url}"
                "/v1/businesses/events"
            ),
            headers=self._headers(),
            json=payload,
            timeout=30.0,
        )

        response.raise_for_status()

        body = response.json()

        if not isinstance(body, dict):
            raise ValueError(
                "Unexpected Explorium "
                "events response"
            )

        raw_events = (
            body.get("output_events")
            or body.get("data")
            or []
        )

        if not isinstance(
            raw_events,
            list,
        ):
            raise ValueError(
                "Explorium events payload "
                "must be a list"
            )

        events: list[
            VibeBusinessEvent
        ] = []

        for raw in raw_events:
            if not isinstance(
                raw,
                dict,
            ):
                continue

            event_type = str(
                raw.get("event_type")
                or raw.get("event_name")
                or "other"
            ).strip()

            data = raw.get("data")

            if not isinstance(
                data,
                dict,
            ):
                data = {}

            source_url = (
                self._source_url(data)
                or self._source_url(raw)
            )

            excerpt = (
                data.get("description")
                or raw.get("description")
                or data.get("summary")
                or raw.get("summary")
            )

            if excerpt is not None:
                excerpt = (
                    str(excerpt).strip()
                    or None
                )

            occurred_at = (
                raw.get("event_time")
                or raw.get("timestamp")
                or raw.get("occurred_at")
            )

            if occurred_at is not None:
                occurred_at = str(
                    occurred_at
                )

            event_id = raw.get(
                "event_id"
            )

            business_id = (
                raw.get("business_id")
                or data.get("business_id")
            )

            events.append(
                VibeBusinessEvent(
                    business_id=(
                        str(business_id)
                        if business_id
                        is not None
                        else None
                    ),
                    event_id=(
                        str(event_id)
                        if event_id
                        is not None
                        else None
                    ),
                    event_type=event_type,
                    title=self._title(
                        event_type,
                        raw,
                    ),
                    occurred_at=occurred_at,
                    source_url=source_url,
                    excerpt=excerpt,
                    raw_data=raw,
                )
            )

        return events
