from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class PublicWebEvidence:
    title: str
    source_url: str
    evidence_type: str
    publisher: str | None = None
    excerpt: str | None = None
    supports_fields: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PublicWebResearchClient:
    """Public-web evidence boundary for verified, non-authenticated sources only."""

    ALLOWED_EVIDENCE_TYPES = {"company_page", "job_page", "news", "search_result", "other"}
    BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}

    @staticmethod
    def validate_source_url(url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("A public HTTP/HTTPS URL is required")

        candidate = url.strip()
        parsed = urlparse(candidate)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()

        if scheme not in {"http", "https"}:
            raise ValueError("A public HTTP/HTTPS URL is required")
        if not host or host in PublicWebResearchClient.BLOCKED_HOSTS:
            raise ValueError("A public HTTP/HTTPS URL is required")
        if host.endswith("linkedin.com"):
            raise ValueError("LinkedIn pages are not valid public-web evidence sources")

        return candidate

    @staticmethod
    def research(
        url: str,
        *,
        evidence_type: str,
        title: str,
        excerpt: str | None = None,
        supports_fields: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        publisher: str | None = None,
    ) -> list[PublicWebEvidence]:
        validated = PublicWebResearchClient.validate_source_url(url)
        if evidence_type not in PublicWebResearchClient.ALLOWED_EVIDENCE_TYPES:
            raise ValueError(f"Unsupported evidence_type: {evidence_type}")
        if not title.strip():
            raise ValueError("Evidence title is required")

        return [
            PublicWebEvidence(
                title=title.strip(),
                source_url=validated,
                evidence_type=evidence_type,
                publisher=publisher,
                excerpt=excerpt.strip() if excerpt else None,
                supports_fields=list(supports_fields or []),
                metadata=dict(metadata or {}),
            )
        ]
