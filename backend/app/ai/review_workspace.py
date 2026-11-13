"""Workspace review case context for LLM match reasoning."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.ai.review_reasoning_schema import (
    RECOMMENDATION_TYPE_LABELS,
    SUMMARY_SECTION_BY_QUEUE,
    normalize_queue_type,
    section_spec,
)
from app.services.review_board import build_review_board


def find_workspace_item(state: Dict[str, Any], *, review_id: Optional[str] = None, item_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    board = build_review_board(state)
    for item in board.get("items") or []:
        if item_id and item.get("id") == item_id:
            return item
        if review_id and (item.get("review_id") == review_id or item.get("id") == review_id):
            return item
    return None


def match_decision_for_item(state: Dict[str, Any], item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    uid = item.get("record_uid")
    if not uid:
        return None
    for row in state.get("match_decisions") or []:
        if row.get("uid") == uid:
            return row
    return None


def _candidate_display_label(row: Dict[str, Any]) -> str:
    name = (row.get("name") or "").strip() or "Unnamed doctor"
    city = (row.get("city") or "").strip()
    return f"{name} · {city}" if city else name


def _humanize_ids(text: str, candidates: List[Dict[str, Any]]) -> str:
    if not text:
        return text
    out = text
    for row in candidates:
        doctor_id = row.get("doctor_id")
        if not doctor_id:
            continue
        label = _candidate_display_label(row)
        out = out.replace(str(doctor_id), label)
    out = re.sub(r"\bHCP-[A-F0-9]{4,}\b", "the alternate candidate", out, flags=re.IGNORECASE)
    out = re.sub(r"\bD\d{3,}\b", "a listed candidate", out)
    return out


def workspace_match_payload(item: Dict[str, Any], decision: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    del decision
    candidates = []
    for row in item.get("candidates") or []:
        candidates.append(
            {
                "doctor_id": row.get("doctor_id"),
                "display_label": _candidate_display_label(row),
                "name": row.get("name"),
                "npi": row.get("npi"),
                "specialty": row.get("specialty"),
                "city": row.get("city"),
                "state": row.get("state"),
                "practice": row.get("practice"),
                "phone": row.get("phone"),
                "recommended": row.get("recommended"),
                "no_clear_winner": row.get("no_clear_winner"),
                "grid": row.get("grid") or {},
                "hard_stops": row.get("hard_stops") or [],
            }
        )
    return {
        "workspace_item_id": item.get("id"),
        "review_id": item.get("review_id"),
        "record_id": item.get("record_id"),
        "queue_type": item.get("queue_type"),
        "question": item.get("question"),
        "link_blocked": bool(item.get("link_blocked")),
        "link_action": item.get("link_action"),
        "case_type": item.get("case_type"),
        "record_snapshot": item.get("record") or {},
        "candidates": candidates,
    }


_PLACEHOLDER_VALUES = frozenset({"", "none", "not available", "n/a", "null"})


def _section_is_missing(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text.lower() in _PLACEHOLDER_VALUES


def _resolve_candidate_label(doctor_id: Optional[str], candidates: List[Dict[str, Any]]) -> Optional[str]:
    if not doctor_id:
        return None
    for row in candidates:
        if row.get("doctor_id") == doctor_id:
            return _candidate_display_label(row)
    return None


def _synthesize_summary_section(
    summary_key: str,
    llm: Dict[str, Any],
    *,
    queue_type: str,
    candidates: List[Dict[str, Any]],
) -> str:
    rec_type = str(llm.get("recommendation_type") or "").strip()
    label = RECOMMENDATION_TYPE_LABELS.get(rec_type, "Manual review required")
    person = _resolve_candidate_label(llm.get("recommended_doctor_id"), candidates)
    reason = str(llm.get("confidence_reason") or "").strip()

    if rec_type == "approve_candidate":
        if person:
            sentence = f"{label}: approve payment for {person} after compliance review."
        else:
            sentence = f"{label}: approve the leading candidate after compliance review."
    elif rec_type == "hold":
        sentence = f"{label}: do not approve until the blocking conflict is cleared."
    elif rec_type == "needs_more_info":
        sentence = f"{label}: gather missing fields before any approval."
    elif rec_type == "reject":
        sentence = f"{label}: leave unmatched or route for manual cleanup."
    else:
        sentence = f"{label}."

    if queue_type == "compliance" and rec_type == "approve_candidate":
        sentence += " Only compliance reviewers can approve; filed Open Payments values are not changed automatically."

    if reason and reason.lower() not in _PLACEHOLDER_VALUES:
        sentence += f" {reason}"

    if summary_key == "match_decision" and person and rec_type == "approve_candidate":
        sentence = f"Link to {person} when identifiers align."

    return _humanize_ids(sentence.strip(), candidates)


def _ensure_summary_sections(
    queue_type: str,
    raw_sections: Dict[str, Any],
    llm: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> None:
    norm = normalize_queue_type(queue_type)
    summary_key = SUMMARY_SECTION_BY_QUEUE.get(norm)
    if not summary_key:
        return
    if _section_is_missing(raw_sections.get(summary_key)):
        raw_sections[summary_key] = _synthesize_summary_section(
            summary_key,
            llm,
            queue_type=queue_type,
            candidates=candidates,
        )


def _fill_sections(
    queue_type: str,
    raw: Dict[str, Any],
    *,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    keys, headings = section_spec(queue_type)
    sections: List[Dict[str, str]] = []
    for key, heading in zip(keys, headings):
        value = raw.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            value = "Not available"
        else:
            value = _humanize_ids(str(value).strip(), candidates or [])
        if not _section_is_missing(value):
            sections.append({"key": key, "heading": heading, "value": value})
    return sections


def merge_llm_reasoning(
    rule: Dict[str, Any],
    llm: Dict[str, Any],
    *,
    queue_type: str,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Normalize LLM JSON into steward UI reasoning. Invalid payload -> valid=False."""
    del rule
    if not isinstance(llm, dict) or not isinstance(llm.get("sections"), dict):
        return {"structured": True, "valid": False, "source": "llm"}

    rec_type = str(llm.get("recommendation_type") or "").strip()
    if rec_type not in RECOMMENDATION_TYPE_LABELS:
        return {"structured": True, "valid": False, "source": "llm"}

    confidence = str(llm.get("confidence") or "").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        return {"structured": True, "valid": False, "source": "llm"}

    confidence_reason = str(llm.get("confidence_reason") or "").strip() or "Not available"
    raw_sections = dict(llm.get("sections") if isinstance(llm.get("sections"), dict) else {})
    keys, _ = section_spec(queue_type)
    cands = candidates or []
    _ensure_summary_sections(queue_type, raw_sections, llm, cands)
    for key in keys:
        if _section_is_missing(raw_sections.get(key)):
            raw_sections[key] = "Not available"

    sections = _fill_sections(queue_type, raw_sections, candidates=cands)
    recommended_doctor_id = llm.get("recommended_doctor_id")
    if recommended_doctor_id is not None:
        recommended_doctor_id = str(recommended_doctor_id).strip() or None

    blocking_raw = raw_sections.get("blocking_conflict") or raw_sections.get("confirm_before_linking") or "the blocking issue"
    blocking = _humanize_ids(str(blocking_raw), cands)

    return {
        "structured": True,
        "valid": True,
        "source": "llm",
        "queue_type": queue_type,
        "recommendation_type": rec_type,
        "recommendation_label": RECOMMENDATION_TYPE_LABELS[rec_type],
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "recommended_doctor_id": recommended_doctor_id,
        "blocking_summary": str(blocking),
        "sections": sections,
    }
