import csv

from app.lead_sources.apollo_csv_provider import ApolloCsvLeadSourceProvider


def write_csv(tmp_path, rows):
    path = tmp_path / "apollo.csv"
    fieldnames = [
        "First Name",
        "Last Name",
        "Title",
        "Company Name",
        "Company Name for Emails",
        "Email",
        "Email Status",
        "Work Direct Phone",
        "Mobile Phone",
        "Corporate Phone",
        "# Employees",
        "Industry",
        "Keywords",
        "Technologies",
        "Person Linkedin Url",
        "Website",
        "Country",
        "Company Country",
        "Apollo Contact Id",
        "Apollo Record Id",
    ]
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_apollo_csv_row_maps_to_normalized_lead(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            {
                "First Name": "Maya",
                "Last Name": "Founder",
                "Title": "Founder",
                "Company Name": "Metric AI",
                "Company Name for Emails": "Metric AI Inc",
                "Email": "maya@metricai.example",
                "Email Status": "Verified",
                "Work Direct Phone": "+15555550100",
                "Mobile Phone": "+15555550101",
                "Corporate Phone": "+15555550102",
                "# Employees": "24",
                "Industry": "SaaS AI software",
                "Keywords": "AI, analytics, revenue intelligence",
                "Technologies": "Python, AWS",
                "Person Linkedin Url": "https://linkedin.com/in/maya-founder",
                "Website": "https://metricai.example",
                "Country": "United States",
                "Company Country": "United States",
                "Apollo Contact Id": "contact-1",
                "Apollo Record Id": "record-1",
            }
        ],
    )

    leads = ApolloCsvLeadSourceProvider(csv_path).fetch_leads()

    assert len(leads) == 1
    lead = leads[0]
    assert lead.person_name == "Maya Founder"
    assert lead.title == "Founder"
    assert lead.company_name == "Metric AI"
    assert lead.company_url == "https://metricai.example"
    assert lead.linkedin_url == "https://linkedin.com/in/maya-founder"
    assert lead.email == "maya@metricai.example"
    assert lead.phone == "+15555550100"
    assert lead.country == "United States"
    assert lead.employee_count == 24
    assert lead.industry == "SaaS AI software"
    assert lead.source == "apollo_csv"
    assert lead.source_id == "contact-1"
    assert lead.raw_source_data["Keywords"] == "AI, analytics, revenue intelligence"
    assert lead.raw_source_data["Technologies"] == "Python, AWS"


def test_apollo_csv_uses_requested_fallbacks(tmp_path):
    csv_path = write_csv(
        tmp_path,
        [
            {
                "First Name": "Omar",
                "Last Name": "CTO",
                "Title": "CTO",
                "Company Name": "",
                "Company Name for Emails": "CareOps AI",
                "Email": "unknown",
                "Email Status": "Unavailable",
                "Work Direct Phone": "",
                "Mobile Phone": "+15555550199",
                "Corporate Phone": "+15555550198",
                "# Employees": "1,250",
                "Industry": "HealthTech",
                "Person Linkedin Url": "https://linkedin.com/in/omar-cto",
                "Website": "https://careops.example",
                "Country": "",
                "Company Country": "United Arab Emirates",
                "Apollo Contact Id": "",
                "Apollo Record Id": "record-2",
            }
        ],
    )

    lead = ApolloCsvLeadSourceProvider(csv_path).fetch_leads()[0]

    assert lead.company_name == "CareOps AI"
    assert lead.email is None
    assert lead.phone == "+15555550199"
    assert lead.country == "United Arab Emirates"
    assert lead.employee_count == 1250
    assert lead.source_id == "record-2"
