import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import CurrentUser, require_user
from app.main import app
from app.repositories.base import RepositoryError
from app.repositories.icp_repository import IcpRepository, icp_repository
from app.schemas.icp import LeadProfile
from app.scoring.icp_engine import IcpScoringEngine


def test_strong_fit_lead_is_scored_against_active_version() -> None:
    engine = IcpScoringEngine(icp_repository.get_active())
    result = engine.score(
        LeadProfile(
            company_name="Scale SaaS",
            annual_revenue=3_000_000,
            employee_count=30,
            country="United States",
            industry="B2B SaaS",
            business_model="SaaS",
            growth_stage="Post-PMF scaling",
            buying_behavior="Retainer-ready with a defined SOW",
            title="CTO",
            has_defined_software_need=True,
            accepts_distributed_delivery=True,
            evidence_urls=["https://example.com/jobs/senior-python"],
        )
    )

    assert result.score == 100
    assert result.disposition == "Strong Fit"
    assert result.tier == "Tier 1"
    assert result.persona == "The Scaling CTO"
    assert result.icp_version == 1
    assert result.evidence_urls == ["https://example.com/jobs/senior-python"]


def test_hard_stop_overrides_other_positive_signals() -> None:
    result = IcpScoringEngine(icp_repository.get_active()).score(
        LeadProfile(
            company_name="Token Startup",
            annual_revenue=900_000,
            employee_count=12,
            country="United States",
            industry="Software",
            business_model="Web3 crypto marketplace",
            growth_stage="Funded",
            buying_behavior="Milestone-based",
            title="Founder",
        )
    )

    assert result.disposition == "Disqualified"
    assert "Business model is explicitly excluded." in result.hard_stops


def test_missing_evidence_is_unknown_instead_of_invented() -> None:
    result = IcpScoringEngine(icp_repository.get_active()).score(
        LeadProfile(company_name="Sparse Evidence Co", title="CEO")
    )

    unknown = [item for item in result.evaluations if item.outcome == "unknown"]
    assert len(unknown) == 7
    assert result.score == 10
    assert result.disposition == "Not Qualified"


@pytest.mark.anyio
async def test_icp_api_lists_version_and_scores_lead() -> None:
    async def override_user() -> CurrentUser:
        return CurrentUser(id="test-user", email="sales@datamart.test", role="sales")

    app.dependency_overrides[require_user] = override_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            versions = await client.get("/icp/versions")
            score = await client.post(
                "/icp/score",
                json={
                    "company_name": "Healthcare Ops",
                    "annual_revenue": 2_000_000,
                    "employee_count": 25,
                    "country": "USA",
                    "industry": "Healthcare",
                    "business_model": "Service-based",
                    "growth_stage": "Established",
                    "buying_behavior": "Milestone-based",
                    "title": "Operations Director"
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert versions.status_code == 200
    assert versions.json()[0]["status"] == "active"
    assert score.status_code == 200
    assert score.json()["persona"] == "The Operations Owner"


def test_icp_draft_publish_preserves_history(tmp_path) -> None:
    repository = IcpRepository(tmp_path)
    repository._write(icp_repository.get_active())

    draft = repository.create_draft(
        {"name": "Datamart Core ICP - Updated", "employee_max": 75}
    )

    assert draft.version == 2
    assert draft.status == "draft"
    assert repository.get_active().version == 1

    published = repository.publish(draft.id, approved_by="Admin User")
    versions = repository.list_versions()

    assert published.status == "active"
    assert published.employee_max == 75
    assert published.approved_by == "Admin User"
    assert {item.status for item in versions} == {"active", "archived"}


def test_icp_repository_raises_domain_error_for_invalid_active_version_state(tmp_path) -> None:
    repository = IcpRepository(tmp_path)

    with pytest.raises(RepositoryError, match="Expected exactly one active ICP version"):
        repository.get_active()

    draft = icp_repository.get_active().model_copy(update={"id": "draft-only", "status": "draft"})
    repository._write(draft)

    with pytest.raises(RepositoryError, match="Expected exactly one active ICP version"):
        repository.get_active()


def test_scoring_evidence_urls_are_normalized_and_deduplicated() -> None:
    result = IcpScoringEngine(icp_repository.get_active()).score(
        LeadProfile(
            company_name="Evidence Verified Co",
            annual_revenue=1_800_000,
            employee_count=18,
            country="United States",
            industry="B2B SaaS",
            business_model="SaaS",
            growth_stage="Post-PMF scaling",
            buying_behavior="Retainer-ready with a defined SOW",
            title="VP of Engineering",
            has_defined_software_need=True,
            accepts_distributed_delivery=True,
            evidence_urls=[
                " https://example.com/jobs/senior-python ",
                "https://example.com/jobs/senior-python",
                "javascript:alert(1)",
                "https://example.com/news/launch",
            ],
        )
    )

    assert result.evidence_urls == [
        "https://example.com/jobs/senior-python",
        "https://example.com/news/launch",
    ]
