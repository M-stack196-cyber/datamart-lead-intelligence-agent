from app.services.vibe_icp_pipeline import (
    prospect_to_lead_profile,
    score_discovered_prospects,
    score_prospect,
)


def strong_fit_prospect():
    return {
        "person_name": "Jane Founder",
        "company_name": "Cloud Labs",
        "company_url": "https://cloudlabs.example",
        "company_type": "privately held",
        "title": "Founder",
        "country": "United States",
        "industry": "SaaS",
        "annual_revenue": 2_000_000,
        "employee_count": 20,
        "growth_stage": "Revenue",
        "business_model": "B2B SaaS",
        "buying_behavior": "Milestone SOW",
        "has_funding_or_revenue": True,
        "has_defined_software_need": True,
        "has_technical_stakeholder": True,
        "accepts_distributed_delivery": True,
        "linkedin_url": (
            "https://linkedin.com/in/"
            "jane-founder"
        ),
    }


def test_prospect_maps_to_icp_profile():
    profile = prospect_to_lead_profile(
        strong_fit_prospect()
    )

    assert profile.company_name == (
        "Cloud Labs"
    )
    assert profile.employee_count == 20
    assert profile.annual_revenue == (
        2_000_000
    )
    assert profile.title == "Founder"
    assert profile.country == (
        "United States"
    )


def test_strong_prospect_scores():
    result = score_prospect(
        strong_fit_prospect()
    )

    assert result.score.icp_id == (
        "datamart-icp-v2"
    )

    assert result.pipeline_status in {
        "qualified",
        "needs_review",
    }


def test_bad_geography_is_not_auto_qualified():
    prospect = strong_fit_prospect()

    prospect["country"] = "Antarctica"

    result = score_prospect(prospect)

    assert result.pipeline_status != (
        "qualified"
    )


def test_batch_separates_results():
    strong = strong_fit_prospect()

    weak = {
        "person_name": "Random Person",
        "company_name": "Unknown Shop",
        "title": "Intern",
        "country": "Unknown",
    }

    batch = score_discovered_prospects(
        [strong, weak]
    )

    total = (
        len(batch.qualified)
        + len(batch.needs_review)
        + len(batch.rejected)
    )

    assert total == 2
