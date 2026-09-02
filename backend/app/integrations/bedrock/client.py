from __future__ import annotations

import json
from dataclasses import dataclass, field
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
