from app.lead_sources import NormalizedLead
from app.services.lead_source_ingestion import (
    dedupe_normalized_leads,
    normalized_lead_to_prospect,
)


def test_normalized_lead_converts_to_scoring_prospect():
    lead = NormalizedLead(
        person_name="Aisha Founder",
        title="Founder",
        company_name="Care AI",
        company_url="https://careai.example",
        linkedin_url="https://linkedin.com/in/aisha",
        email="aisha@careai.example",
        phone="+15555550100",
        country="United States",
        employee_count=12,
        industry="HealthTech",
        source="apollo",
        source_id="person-1",
        raw_source_data={"id": "person-1"},
    )

    prospect = normalized_lead_to_prospect(lead)

    assert prospect["lead_source"] == "apollo"
    assert prospect["apollo_person_id"] == "person-1"
    assert prospect["raw_source_data"] == {"id": "person-1"}


def test_normalized_lead_dedupe_uses_cross_provider_identity_rules():
    first = NormalizedLead(
        person_name="Aisha Founder",
        company_url="https://www.careai.example/",
        linkedin_url="https://linkedin.com/in/aisha",
        email="aisha@careai.example",
        source="apollo",
        source_id="person-1",
        raw_source_data={"id": "person-1"},
    )
    duplicate = first.model_copy(update={"source_id": "person-2"})
    colleague = first.model_copy(
        update={
            "person_name": "Omar CTO",
            "linkedin_url": "https://linkedin.com/in/omar",
            "email": "omar@careai.example",
            "source_id": "person-3",
        }
    )

    unique, duplicate_count = dedupe_normalized_leads([first, duplicate, colleague])

    assert unique == [first, colleague]
    assert duplicate_count == 1
