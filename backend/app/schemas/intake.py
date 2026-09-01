from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


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
        if value is None or value == "":
            return None
        normalized = value.split("?", 1)[0].rstrip("/")
        if not normalized.lower().startswith(("https://linkedin.com/in/", "https://www.linkedin.com/in/")):
            raise ValueError("linkedin_url must be a LinkedIn profile URL")
        return normalized

    @model_validator(mode="after")
    def require_identity(self) -> "LeadIntakeRow":
        if not self.linkedin_url and not self.company_url and not self.company_name:
            raise ValueError("LinkedIn URL, company URL, or company name is required")
        return self


class LeadIntakeBatch(BaseModel):
    rows: list[LeadIntakeRow] = Field(min_length=1, max_length=100)


class LeadIntakeValidation(BaseModel):
    valid: bool
    count: int
    rows: list[LeadIntakeRow]
