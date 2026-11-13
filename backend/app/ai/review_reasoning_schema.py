"""Structured review workspace reasoning sections per queue."""

from __future__ import annotations

from typing import Dict, List, Literal, Tuple

QueueType = Literal["compliance", "identity", "safety", "proposed", "proposed_changes", "unmatched"]

SECTION_KEYS: Dict[str, List[str]] = {
    "compliance": [
        "evidence",
        "blocking_conflict",
        "alternate_candidate",
        "missing_evidence",
        "reviewer_action",
        "recommendation",
    ],
    "identity": [
        "score_drivers",
        "conflicting_fields",
        "alternates_ruled_out",
        "confirm_before_linking",
        "match_decision",
    ],
    "safety": [
        "risk_signal",
        "source_of_signal",
        "clinical_reviewer_required",
        "hold_status",
        "action",
    ],
    "proposed_changes": [
        "current_value",
        "proposed_value",
        "source_of_proposal",
        "risk_if_applied",
        "reviewer_decision",
    ],
}

SECTION_HEADINGS: Dict[str, List[str]] = {
    "compliance": [
        "Evidence",
        "Blocking conflict",
        "Alternate candidate",
        "Missing evidence",
        "Reviewer action",
        "Recommendation",
    ],
    "identity": [
        "Score drivers",
        "Conflicting fields",
        "Alternates ruled out",
        "Confirm before linking",
        "Match decision",
    ],
    "safety": [
        "Risk signal",
        "Source of signal",
        "Clinical reviewer required",
        "Hold status",
        "Action",
    ],
    "proposed_changes": [
        "Current value",
        "Proposed value",
        "Source of proposal",
        "Risk if applied",
        "Reviewer decision",
    ],
}

RECOMMENDATION_TYPE_LABELS = {
    "approve_candidate": "Approve candidate",
    "hold": "Hold, do not link",
    "needs_more_info": "Needs more information",
    "reject": "Reject linking",
}


def normalize_queue_type(queue_type: str) -> str:
    if queue_type == "proposed":
        return "proposed_changes"
    if queue_type == "unmatched":
        return "identity"
    if queue_type in SECTION_KEYS:
        return queue_type
    return "identity"


def section_spec(queue_type: str) -> Tuple[List[str], List[str]]:
    key = normalize_queue_type(queue_type)
    return SECTION_KEYS[key], SECTION_HEADINGS[key]


SUMMARY_SECTION_BY_QUEUE: Dict[str, str] = {
    "compliance": "recommendation",
    "identity": "match_decision",
    "safety": "action",
    "proposed_changes": "reviewer_decision",
}
