import pytest

from app.integrations.public_web import PublicWebEvidence, PublicWebResearchClient


def test_public_web_research_rejects_unsafe_urls() -> None:
    with pytest.raises(ValueError, match="public HTTP/HTTPS URL"):
        PublicWebResearchClient.validate_source_url("javascript:alert(1)")

    with pytest.raises(ValueError, match="public HTTP/HTTPS URL"):
        PublicWebResearchClient.validate_source_url("http://localhost:8000/secret")


def test_public_web_research_builds_evidence_only_from_verified_sources() -> None:
    evidence = PublicWebResearchClient().research(
        "https://www.datamart.io/careers/senior-engineer",
        evidence_type="job_page",
        title="Senior Engineer at Datamart",
        excerpt="Datamart is hiring a senior engineer to build the lead intelligence platform.",
        supports_fields=["company_name", "title"],
        metadata={"source": "public-web"},
    )

    assert isinstance(evidence, list)
    assert len(evidence) == 1
    item = evidence[0]
    assert isinstance(item, PublicWebEvidence)
    assert item.evidence_type == "job_page"
    assert item.source_url == "https://www.datamart.io/careers/senior-engineer"
    assert item.supports_fields == ["company_name", "title"]
    assert item.metadata["source"] == "public-web"
