"""Shared person-level discovery identities (mirrored by the ingest SQL helpers)."""
import re
from typing import Any
from urllib.parse import unquote, urlsplit


def normalized_name(value: Any) -> str:
    return re.sub(r"[^\w]+", " ", str(value or "").lower(), flags=re.UNICODE).strip()


def normalized_id(value: Any) -> str:
    return str(value or "").strip().lower()


def normalized_url(value: Any) -> str:
    raw = unquote(str(value or "").strip()).lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = re.sub(r"^www\.", "", raw)
    return re.split(r"[?#]", raw, maxsplit=1)[0].rstrip("/")


def company_host(value: Any) -> str:
    try:
        raw = unquote(str(value or "").strip())
        parsed = urlsplit(raw if "://" in raw else "https://" + raw)
        return (parsed.hostname or "").lower().removeprefix("www.").rstrip(".")
    except ValueError:
        return ""


def prospect_identities(prospect: dict[str, Any]) -> set[tuple[str, ...]]:
    """Company identities include a person; colleagues must remain separate leads."""
    keys: set[tuple[str, ...]] = set()
    person = normalized_name(prospect.get("person_name"))
    prospect_id = normalized_id(prospect.get("vibe_prospect_id") or prospect.get("prospect_id"))
    business_id = normalized_id(prospect.get("vibe_business_id") or prospect.get("business_id"))
    linkedin = normalized_url(prospect.get("linkedin_url"))
    company_url = normalized_url(prospect.get("company_url") or prospect.get("company_website"))
    company_name = normalized_name(prospect.get("company_name"))
    if prospect_id:
        keys.add(("prospect", prospect_id))
    if linkedin:
        keys.add(("linkedin", linkedin))
    if person:
        if business_id:
            keys.add(("business_person", business_id, person))
        if company_url:
            keys.add(("website_person", company_url, person))
        if company_name:
            keys.add(("company_person", company_name, person))
    return keys
