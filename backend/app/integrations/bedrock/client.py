from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class BedrockAnalysis:
    summary: str
    key_findings: list[str] = field(default_factory=list)
    draft_message: str = ""
    confidence: float = 0.0
    risks: list[str] = field(default_factory=list)
    evidence_urls: list[str] = field(default_factory=list)
    score: int | None = None
    disposition: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "key_findings": self.key_findings,
            "draft_message": self.draft_message,
            "confidence": self.confidence,
            "risks": self.risks,
            "evidence_urls": self.evidence_urls,
            "score": self.score,
            "disposition": self.disposition,
            "raw_response": self.raw_response,
        }


class BedrockClient:
    """AWS Bedrock adapter for evidence-grounded lead analysis and drafting."""

    SAFE_FIELDS = {"summary", "key_findings", "draft_message", "confidence", "risks"}
    OUTREACH_FIELDS = {
        "subject",
        "body",
        "personalization_summary",
        "evidence_refs",
        "grounding_warnings",
        "evidence_coverage",
    }

    def __init__(self, api_token: str, model_id: str, *, base_url: str = "https://bedrock-runtime.us-east-1.amazonaws.com") -> None:
        if not api_token or not model_id:
            raise ValueError("AWS Bedrock credentials required")
        self.api_token = api_token
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            raise ValueError("Unexpected Bedrock response shape")
        output = payload.get("output")
        if not isinstance(output, dict):
            raise ValueError("Unexpected Bedrock response shape")
        message = output.get("message")
        if not isinstance(message, dict):
            raise ValueError("Unexpected Bedrock response shape")
        content = message.get("content")
        if not isinstance(content, list) or not content:
            raise ValueError("Unexpected Bedrock response shape")
        first = content[0]
        if not isinstance(first, dict):
            raise ValueError("Unexpected Bedrock response shape")
        text = first.get("text")
        if not isinstance(text, str):
            raise ValueError("Unexpected Bedrock response shape")
        return text

    def analyze(self, lead: dict[str, Any], score: dict[str, Any], evidence: list[dict[str, Any]]) -> BedrockAnalysis:
        prompt = (
            "You are a sales research analyst. Provide a brief, evidence-grounded analysis of this lead. "
            "Return JSON with only: summary, key_findings, draft_message, confidence, risks. "
            "Do not invent contact details or override the score."
        )
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": json.dumps({
                        "lead": {
                            "person_name": lead.get("person_name"),
                            "company_name": lead.get("company_name"),
                            "title": lead.get("title"),
                            "linkedin_url": lead.get("linkedin_url"),
                        },
                        "score": score,
                        "evidence": evidence,
                    })},
                    {"type": "text", "text": prompt},
                ]}
            ],
        }

        response = httpx.post(
            f"{self.base_url}/model/{self.model_id}/invoke",
            headers={"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json()
        text = self._extract_text(raw)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Bedrock returned invalid JSON") from exc

        if not isinstance(parsed, dict):
            raise ValueError("Bedrock returned a non-object JSON payload")

        filtered = {
            key: value for key, value in parsed.items() if key in self.SAFE_FIELDS
        }
        safe_summary = str(filtered.get("summary") or "Analysis unavailable")
        key_findings = filtered.get("key_findings")
        if not isinstance(key_findings, list):
            key_findings = []
        draft_message = str(filtered.get("draft_message") or "")
        confidence = filtered.get("confidence")
        risks = filtered.get("risks")
        if not isinstance(risks, list):
            risks = []

        return BedrockAnalysis(
            summary=safe_summary,
            key_findings=[str(item) for item in key_findings],
            draft_message=draft_message,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.0,
            risks=[str(item) for item in risks],
            evidence_urls=[str(item.get("source_url")) for item in evidence if isinstance(item, dict) and item.get("source_url")],
            score=score.get("score") if isinstance(score, dict) else None,
            disposition=score.get("disposition") if isinstance(score, dict) else None,
            raw_response=raw,
        )

    def generate_outreach_message(
        self,
        lead: dict[str, Any],
        evidence: list[dict[str, Any]],
        *,
        icp_score: int | None = None,
        icp_disposition: str | None = None,
        matched_criteria: list[str] | None = None,
        intent_score: int | None = None,
        intent_level: str | None = None,
        intent_signals: list[str] | None = None,
    ) -> dict[str, Any]:
        prompt = (
            "You are a careful sales outreach writer. Draft a short, professional email using only facts supported by the evidence list. "
            "Never invent company facts, hiring activity, funding, technology, growth, employee counts, revenue, initiatives, or pain points. "
            "If the evidence is weak, use a more generic but professional message. "
            "Return JSON with only: subject, body, personalization_summary, evidence_refs, grounding_warnings, evidence_coverage."
        )
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": json.dumps({
                        "lead": {
                            "person_name": lead.get("person_name"),
                            "company_name": lead.get("company_name"),
                            "title": lead.get("title"),
                            "industry": lead.get("industry"),
                            "country": lead.get("country"),
                            "email": lead.get("email"),
                            "linkedin_url": lead.get("linkedin_url"),
                            "company_url": lead.get("company_url"),
                        },
                        "icp": {"score": icp_score, "disposition": icp_disposition},
                        "matched_criteria": matched_criteria or [],
                        "intent": {"score": intent_score, "level": intent_level},
                        "intent_signals": intent_signals or [],
                        "evidence": evidence,
                    })},
                    {"type": "text", "text": prompt},
                ]}
            ],
        }

        response = httpx.post(
            f"{self.base_url}/model/{self.model_id}/invoke",
            headers={"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json()
        text = self._extract_text(raw)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Bedrock returned invalid JSON") from exc

        if not isinstance(parsed, dict):
            raise ValueError("Bedrock returned a non-object JSON payload")

        filtered = {key: value for key, value in parsed.items() if key in self.OUTREACH_FIELDS}
        subject = str(filtered.get("subject") or "Quick question").strip() or "Quick question"
        body = str(filtered.get("body") or "").strip()
        if not body:
            raise ValueError("Bedrock returned an empty outreach body")
        personalization_summary = str(filtered.get("personalization_summary") or "").strip() or "Evidence-grounded outreach draft"
        evidence_refs = filtered.get("evidence_refs")
        if not isinstance(evidence_refs, list):
            evidence_refs = [str(item.get("id")) for item in evidence if isinstance(item, dict) and item.get("id")]
        evidence_refs = [str(item) for item in evidence_refs][:10]
        grounding_warnings = filtered.get("grounding_warnings")
        if not isinstance(grounding_warnings, list):
            grounding_warnings = []
        coverage = filtered.get("evidence_coverage")
        if coverage not in {"full", "partial", "insufficient"}:
            coverage = "partial" if evidence else "insufficient"

        return {
            "subject": subject,
            "body": body,
            "personalization_summary": personalization_summary,
            "evidence_refs": evidence_refs,
            "grounding_warnings": [str(item) for item in grounding_warnings],
            "evidence_coverage": coverage,
            "provider": "bedrock",
            "model": self.model_id,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "raw_response": raw,
        }
