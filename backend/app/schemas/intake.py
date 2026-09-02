from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


def canonicalize_linkedin_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None

    candidate = value.strip()
    candidate = candidate.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if not candidate:
        return None

    parsed = urlparse(candidate)
    host = (parsed.netloc or parsed.path).lower().removeprefix("www.")
    path = parsed.path or candidate
    if host not in {"linkedin.com", "www.linkedin.com"}:
        return candidate
    if not path.startswith("/in/"):
        return candidate
    username = path[len("/in/") :]
    if not username:
        return candidate
    return f"https://www.linkedin.com/in/{username.lower()}"


class LeadIntakeRow(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    linkedin_url: str | None = None
    company_name: str | None = Field(default=None, max_length=200)
    person_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    company_url: str | None = None
    email: EmailStr | None = None
    country: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=150)

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin_profile(cls, value: str | None) -> str | None:
        normalized = canonicalize_linkedin_url(value)
        if normalized is None:
            return None
        if not normalized.lower().startswith("https://www.linkedin.com/in/"):
            raise ValueError("linkedin_url must be a LinkedIn profile URL")
        return normalized

    @model_validator(mode="after")
    def require_identity(self) -> "LeadIntakeRow":
        if not self.linkedin_url and not self.company_url and not self.company_name:
            raise ValueError("LinkedIn URL, company URL, or company name is required")
        return self


class LeadIntakeBatch(BaseModel):
    rows: list[LeadIntakeRow] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def reject_duplicate_linkedin_urls(self) -> "LeadIntakeBatch":
        seen: set[str] = set()
        for row in self.rows:
            normalized = canonicalize_linkedin_url(row.linkedin_url)
            if normalized is None:
                continue
            key = normalized.lower().rstrip("/")
            if key in seen:
                raise ValueError("Duplicate LinkedIn profile URL detected in the same batch")
            seen.add(key)
        return self


class LeadIntakeValidation(BaseModel):
    valid: bool
    count: int
    rows: list[LeadIntakeRow]
