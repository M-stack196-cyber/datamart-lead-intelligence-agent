import pytest
from pydantic import ValidationError

from app.schemas.intake import LeadIntakeBatch, LeadIntakeRow


def test_linkedin_profile_is_normalized() -> None:
    row = LeadIntakeRow(linkedin_url=" https://www.linkedin.com/in/example-person/?trk=public ")
    assert row.linkedin_url == "https://www.linkedin.com/in/example-person"


def test_row_requires_a_researchable_identity() -> None:
    with pytest.raises(ValidationError):
        LeadIntakeRow(person_name="Unknown")


def test_batch_is_limited_to_daily_mvp_size() -> None:
    rows = [LeadIntakeRow(company_name=f"Company {index}") for index in range(101)]
    with pytest.raises(ValidationError):
        LeadIntakeBatch(rows=rows)


def test_company_only_row_is_valid_for_csv_intake() -> None:
    row = LeadIntakeRow(company_name="Datamart prospect", company_url="https://example.com")
    assert row.company_name == "Datamart prospect"


def test_duplicate_linkedin_urls_in_same_batch_are_rejected() -> None:
    rows = [
        LeadIntakeRow(linkedin_url="https://www.linkedin.com/in/example-person"),
        LeadIntakeRow(linkedin_url="https://linkedin.com/in/example-person/?utm=1"),
    ]
    with pytest.raises(ValidationError):
        LeadIntakeBatch(rows=rows)
