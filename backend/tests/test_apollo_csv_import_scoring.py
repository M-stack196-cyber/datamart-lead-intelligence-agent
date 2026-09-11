import csv

from app.lead_sources.apollo_csv_provider import ApolloCsvLeadSourceProvider
from app.services.lead_source_ingestion import prepare_and_score_leads


def write_csv(tmp_path, rows):
    path = tmp_path / "apollo-scoring.csv"
    fieldnames = [
        "First Name",
        "Last Name",
        "Title",
        "Company Name",
        "Company Name for Emails",
        "Email",
        "Email Status",
        "# Employees",
        "Industry",
        "Keywords",
        "Technologies",
        "Person Linkedin Url",
        "Website",
        "Country",
        "Apollo Contact Id",
        "Apollo Record Id",
        "Annual Revenue",
    ]
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_apollo_csv_strong_founder_scores_above_40(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            {
                "First Name": "Maya",
                "Last Name": "Founder",
                "Title": "Founder",
                "Company Name": "Metric AI",
                "Email": "maya@metricai.example",
                "Email Status": "Verified",
                "# Employees": "24",
                "Industry": "SaaS AI software",
                "Keywords": "B2B SaaS, AI analytics, revenue intelligence",
                "Technologies": "AWS, Python, Snowflake",
                "Person Linkedin Url": "https://linkedin.com/in/maya-founder",
                "Website": "https://metricai.example",
                "Country": "United States",
                "Apollo Contact Id": "contact-1",
                "Annual Revenue": "$2500000",
            }
        ],
    )

    result = prepare_and_score_leads(ApolloCsvLeadSourceProvider(csv_path).fetch_leads())
    scored = result.scored[0]

    assert result.requested_count == 1
    assert result.prepared_count == 1
    assert scored.score.score > 40
    assert scored.pipeline_status in {"qualified", "needs_review"}


def test_apollo_csv_weak_non_icp_row_scores_lower_or_is_not_qualified(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            {
                "First Name": "Pat",
                "Last Name": "Intern",
                "Title": "Intern",
                "Company Name": "Example University",
                "Email": "pat@example.edu",
                "Email Status": "Verified",
                "# Employees": "200",
                "Industry": "Education",
                "Person Linkedin Url": "https://linkedin.com/in/pat-intern",
                "Website": "https://example.edu",
                "Country": "Canada",
                "Apollo Contact Id": "contact-2",
            }
        ],
    )

    result = prepare_and_score_leads(ApolloCsvLeadSourceProvider(csv_path).fetch_leads())
    scored = result.scored[0]

    assert scored.score.score <= 40
    assert scored.pipeline_status in {"rejected", "needs_review"}
    assert scored.pipeline_status != "qualified"
