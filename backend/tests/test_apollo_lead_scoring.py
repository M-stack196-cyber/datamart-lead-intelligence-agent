from app.lead_sources import NormalizedLead
from app.services.lead_source_ingestion import prepare_and_score_leads


def test_apollo_saas_ai_founder_scores_above_40_and_stays_review_without_revenue():
    lead = NormalizedLead(
        person_name="Maya Founder",
        title="Founder",
        company_name="Metric AI",
        company_url="https://metricai.example",
        linkedin_url="https://linkedin.com/in/maya-founder",
        email="maya@metricai.example",
        country="United States",
        employee_count=24,
        industry="SaaS AI software",
        source="apollo",
        source_id="person-1",
        raw_source_data={
            "id": "person-1",
            "organization": {
                "description": "B2B SaaS AI analytics platform for revenue teams",
                "website_url": "https://metricai.example",
            },
        },
    )

    result = prepare_and_score_leads([lead])
    scored = result.scored[0]

    assert scored.score.score > 40
    assert scored.pipeline_status == "needs_review"
    assert "Company size/revenue missing" in " ".join(scored.score.review_reasons)


def test_apollo_non_icp_lead_remains_rejected_or_review():
    lead = NormalizedLead(
        person_name="Pat Intern",
        title="Intern",
        company_name="Example University",
        company_url="https://example.edu",
        linkedin_url="https://linkedin.com/in/pat-intern",
        country="Canada",
        employee_count=200,
        industry="Education",
        source="apollo",
        source_id="person-2",
        raw_source_data={"id": "person-2"},
    )

    result = prepare_and_score_leads([lead])
    scored = result.scored[0]

    assert scored.score.score <= 40
    assert scored.pipeline_status in {"rejected", "needs_review"}
    assert scored.pipeline_status != "qualified"
