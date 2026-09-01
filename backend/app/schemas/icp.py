from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IcpStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ScoringRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    weight: int = Field(ge=0, le=100)
    description: str


class HardStopRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    description: str


class PersonaDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    titles: list[str]
    company_profile: str
    triggers: list[str]
    resonates: list[str]
    repels: list[str]


class TierDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    revenue_min: int
    revenue_max: int
    employees_min: int
    employees_max: int
    description: str


class IcpDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    version: int = Field(ge=1)
    status: IcpStatus
    source: str
    effective_date: str
    approved_by: str | None = None
    target_countries: list[str]
    target_industries: list[str]
    excluded_company_types: list[str]
    excluded_business_models: list[str]
    revenue_min: int
    revenue_max: int
    employee_min: int
    employee_max: int
    accepted_growth_stages: list[str]
    accepted_business_models: list[str]
    accepted_buying_behaviors: list[str]
    decision_maker_titles: list[str]
    scoring_rules: list[ScoringRule]
    hard_stops: list[HardStopRule]
    personas: list[PersonaDefinition]
    tiers: list[TierDefinition]


class IcpVersionSummary(BaseModel):
    id: str
    name: str
    version: int
    status: IcpStatus
    effective_date: str
    source: str


class LeadProfile(BaseModel):
    company_name: str
    annual_revenue: int | None = Field(default=None, ge=0)
    employee_count: int | None = Field(default=None, ge=0)
    country: str | None = None
    industry: str | None = None
    business_model: str | None = None
    growth_stage: str | None = None
    buying_behavior: str | None = None
    title: str | None = None
    has_funding_or_revenue: bool | None = None
    has_defined_software_need: bool | None = None
    has_technical_stakeholder: bool | None = None
    accepts_distributed_delivery: bool | None = None
    evidence_urls: list[str] = Field(default_factory=list)


class RuleEvaluation(BaseModel):
    rule_key: str
    label: str
    outcome: Literal["matched", "missing", "failed", "unknown"]
    points_awarded: int
    points_available: int
    explanation: str


class ScoreResult(BaseModel):
    company_name: str
    icp_id: str
    icp_version: int
    score: int
    disposition: Literal["Strong Fit", "Good Fit", "Review", "Not Qualified", "Disqualified"]
    tier: Literal["Tier 1", "Tier 2", "Tier 3", "Unassigned"]
    persona: str | None
    hard_stops: list[str]
    evaluations: list[RuleEvaluation]
    evidence_urls: list[str]
