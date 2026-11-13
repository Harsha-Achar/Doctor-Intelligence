from __future__ import annotations

import json

import pytest

from app.ai.results import ReviewExplanationResult
from app.ai.review_workspace import merge_llm_reasoning


def _p3305_llm() -> dict:
    return {
        "recommendation_type": "hold",
        "confidence": "low",
        "confidence_reason": "conflicting identifier",
        "recommended_doctor_id": None,
        "sections": {
            "recommendation": "Hold payment approval until the NPI field dispute is resolved.",
            "evidence": "The Name field matches William Harris Jr.",
            "blocking_conflict": "The NPI field is conflicting for William Harris Jr versus William Harris Sr.",
            "alternate_candidate": "William Harris Sr is weaker on Suffix field and Practice field.",
            "missing_evidence": "None",
            "reviewer_action": "Check NPI 1500605765 against the NPPES registry.",
        },
        "requires_human_review": True,
    }


def test_review_explanation_schema_accepts_structured_payload():
    payload = _p3305_llm()
    parsed = ReviewExplanationResult.model_validate(payload)
    assert parsed.recommendation_type == "hold"
    assert parsed.sections["blocking_conflict"].startswith("The NPI field is conflicting")


def test_merge_compliance_omits_empty_sections():
    llm = dict(_p3305_llm())
    del llm["sections"]["missing_evidence"]
    merged = merge_llm_reasoning({}, llm, queue_type="compliance")
    assert merged["valid"] is True
    keys = {row["key"] for row in merged["sections"]}
    assert "missing_evidence" not in keys
    assert "evidence" in keys


def test_merge_invalid_llm_returns_unavailable():
    merged = merge_llm_reasoning({}, {"sections": {}}, queue_type="compliance")
    assert merged["valid"] is False


def test_merge_synthesizes_missing_recommendation():
    llm = {
        "recommendation_type": "approve_candidate",
        "confidence": "high",
        "confidence_reason": "NPI field aligns.",
        "recommended_doctor_id": "HCP-1",
        "sections": {
            "evidence": "NPI field matches.",
            "blocking_conflict": "None",
            "alternate_candidate": "Weaker NPI.",
            "missing_evidence": "Practice missing.",
            "reviewer_action": "Check NPI registry.",
        },
    }
    candidates = [{"doctor_id": "HCP-1", "name": "Priya Sharma", "city": "Atlanta"}]
    merged = merge_llm_reasoning({}, llm, queue_type="compliance", candidates=candidates)
    rec = next(row for row in merged["sections"] if row["key"] == "recommendation")
    assert rec["value"] != "Not available"
    assert "Priya Sharma" in rec["value"]


def test_merge_replaces_internal_ids_with_names():
    llm = {
        "recommendation_type": "hold",
        "confidence": "low",
        "confidence_reason": "npi",
        "sections": {
            "evidence": "HCP-950CA2E4 matches the NPI field.",
            "blocking_conflict": "HCP-566528CD has a conflicting NPI field.",
            "alternate_candidate": "None",
            "missing_evidence": "None",
            "reviewer_action": "Check NPI.",
            "recommendation": "Hold.",
        },
    }
    candidates = [
        {"doctor_id": "HCP-950CA2E4", "name": "William Harris Jr", "city": "Boston"},
        {"doctor_id": "HCP-566528CD", "name": "William Harris Sr", "city": "Boston"},
    ]
    merged = merge_llm_reasoning({}, llm, queue_type="compliance", candidates=candidates)
    blob = " ".join(row["value"] for row in merged["sections"])
    assert "HCP-" not in blob
    assert "William Harris Jr · Boston" in blob
    assert "William Harris Sr · Boston" in blob


def test_p3305_hold_does_not_use_points_to_language():
    merged = merge_llm_reasoning({}, _p3305_llm(), queue_type="compliance")
    blob = json.dumps(merged)
    assert "points to" not in blob.lower()
    assert merged["recommendation_type"] == "hold"


@pytest.mark.parametrize(
    "queue_type,expected_first",
    [
        ("compliance", "Evidence"),
        ("identity", "Score drivers"),
        ("safety", "Risk signal"),
        ("proposed", "Current value"),
    ],
)
def test_queue_section_headings(queue_type, expected_first):
    seed = {
        "compliance": {"evidence": "NPI field conflicts."},
        "identity": {"score_drivers": "Name field matches."},
        "safety": {"risk_signal": "Possible adverse event."},
        "proposed": {"current_value": "Old phone."},
    }[queue_type]
    merged = merge_llm_reasoning(
        {},
        {
            "recommendation_type": "hold",
            "confidence": "low",
            "confidence_reason": "test",
            "sections": seed,
        },
        queue_type=queue_type,
    )
    assert merged["sections"][0]["heading"] == expected_first
