import csv
from types import SimpleNamespace

from scripts import import_apollo_csv


def write_csv(tmp_path):
    path = tmp_path / "apollo.csv"
    fieldnames = [
        "First Name",
        "Last Name",
        "Title",
        "Company Name",
        "Email",
        "Email Status",
        "# Employees",
        "Industry",
        "Person Linkedin Url",
        "Website",
        "Country",
        "Apollo Contact Id",
    ]
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "First Name": "Maya",
                "Last Name": "Founder",
                "Title": "Founder",
                "Company Name": "Metric AI",
                "Email": "maya@metricai.example",
                "Email Status": "Verified",
                "# Employees": "24",
                "Industry": "SaaS AI software",
                "Person Linkedin Url": "https://linkedin.com/in/maya-founder",
                "Website": "https://metricai.example",
                "Country": "United States",
                "Apollo Contact Id": "contact-1",
            }
        )
    return path


def test_apollo_csv_dry_run_does_not_call_persistence(tmp_path, monkeypatch):
    csv_path = write_csv(tmp_path)
    persist = monkeypatch.setattr(
        import_apollo_csv,
        "persist_scored_leads",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not persist")),
    )
    client = monkeypatch.setattr(
        import_apollo_csv,
        "service_role_client",
        lambda: (_ for _ in ()).throw(AssertionError("should not create client")),
    )

    assert import_apollo_csv.main(["--file", str(csv_path), "--dry-run"]) == 0
    assert persist is None
    assert client is None


def test_apollo_csv_non_dry_run_calls_persistence(tmp_path, monkeypatch):
    csv_path = write_csv(tmp_path)
    calls = {}

    monkeypatch.setattr(import_apollo_csv, "service_role_client", lambda: "client")

    def fake_persist(client, result, *, file_name):
        calls["client"] = client
        calls["requested_count"] = result.requested_count
        calls["file_name"] = file_name
        return SimpleNamespace(
            inserted_count=1,
            updated_count=0,
            duplicate_count=0,
            errors=[],
            warnings=[],
        )

    monkeypatch.setattr(import_apollo_csv, "persist_scored_leads", fake_persist)

    assert import_apollo_csv.main(["--file", str(csv_path)]) == 0
    assert calls == {
        "client": "client",
        "requested_count": 1,
        "file_name": "apollo.csv",
    }
