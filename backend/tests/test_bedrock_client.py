from unittest.mock import Mock, patch

import pytest

from app.integrations.bedrock import BedrockClient


def test_bedrock_client_requires_credentials() -> None:
    with pytest.raises(ValueError, match="AWS Bedrock credentials required"):
        BedrockClient(api_token="", model_id="test-model")

    with pytest.raises(ValueError, match="AWS Bedrock credentials required"):
        BedrockClient(api_token="token", model_id="")


def test_bedrock_client_generates_evidence_based_analysis() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "output": {
            "message": {
                "content": [
                    {"text": '{"summary":"Strong fit with clear signal from public evidence.","key_findings":["The company is a SaaS vendor","The founder is active in product marketing"],"draft_message":"Hi Aisha, I saw your product work and the company focus aligns with our ICP.","confidence":0.84,"risks":["No direct email was validated"]}' }
                ]
            }
        }
    }

    lead = {
        "person_name": "Aisha Rafiq",
        "company_name": "Datamart",
        "title": "Founder",
        "linkedin_url": "https://linkedin.com/in/aisha",
    }
    score = {"score": 82, "disposition": "Strong Fit", "hard_stops": []}
    evidence = [{"title": "Founder profile", "source_url": "https://example.com/founder"}, {"title": "Company page", "source_url": "https://example.com/company"}]

    with patch("app.integrations.bedrock.client.httpx.post", return_value=response) as post:
        analysis = BedrockClient(api_token="token", model_id="model-id").analyze(lead, score, evidence)

    assert analysis.summary == "Strong fit with clear signal from public evidence."
    assert analysis.confidence == 0.84
    assert analysis.draft_message.startswith("Hi Aisha")
    assert analysis.evidence_urls == ["https://example.com/founder", "https://example.com/company"]
    assert analysis.score == 82
    assert analysis.disposition == "Strong Fit"
    assert "annual_revenue" not in analysis.model_dump()
    assert post.call_count == 1


def test_bedrock_client_generates_structured_grounded_outreach() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"output": {"message": {"content": [{"text": (
        '{"subject":"A relevant question","body":"Hi Aisha, would a brief conversation be useful?",'
        '"evidence_refs":["evidence-1"],"grounding_warnings":[],"evidence_coverage":"full"}'
    )}]}}}
    lead = {"person_name": "Aisha", "company_name": "Datamart",
            "company_url": "https://datamart.example"}
    evidence = [{"id": "evidence-1", "title": "Company update",
                 "source_url": "https://example.com/update"}]

    with patch("app.integrations.bedrock.client.httpx.post", return_value=response) as post:
        result = BedrockClient("token", "model-id").generate_outreach_message(
            lead, evidence, icp_score=82, icp_disposition="Strong Fit",
            matched_criteria=["Decision-maker"], intent_score=71, intent_level="high",
            intent_signals=["Stored public update"],
        )

    sent = post.call_args.kwargs["json"]
    prompt_context = sent["messages"][0]["content"][0]["text"]
    assert '"score": 82' in prompt_context
    assert '"company_url": "https://datamart.example"' in prompt_context
    assert result["evidence_refs"] == ["evidence-1"]
    assert result["evidence_coverage"] == "full"
    assert result["provider"] == "bedrock"
