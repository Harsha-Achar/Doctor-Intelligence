from __future__ import annotations

import json
from pathlib import Path

from app.services.review_board import build_review_board


def _board():
    state_path = Path(__file__).resolve().parents[1] / "data" / "runtime" / "state.json"
    state = json.loads(state_path.read_text())
    return build_review_board(state)


def _practice_subtext(record_id: str, doctor_name: str) -> tuple[str, str]:
    item = next(row for row in _board()["items"] if row.get("record_id") == record_id)
    cand = next(c for c in item["candidates"] if (c.get("name") or "") == doctor_name)
    symbol, detail = (cand.get("grid") or {}).get("Practice", ["—", ""])
    return symbol, detail


def test_clm_55102_practice_row_subtext():
    assert _practice_subtext("CLM-55102", "Sarah Lee-Kim") == ("✓", "Organization matches")
    assert _practice_subtext("CLM-55102", "Sarah Lee") == ("✗", "Organization differs")
    assert _practice_subtext("CLM-55102", "Sara Li") == ("✗", "Organization differs")


def test_crm_9400_practice_row_subtext():
    assert _practice_subtext("CRM-9400", "Priya Sharma") == ("✓", "Organization matches")
    # Two doctors same display name — pick by highest score NPI match row order
    item = next(row for row in _board()["items"] if row.get("record_id") == "CRM-9400")
    alts = [c for c in item["candidates"] if c.get("npi") == "1576634514"]
    assert len(alts) == 1
    symbol, detail = (alts[0].get("grid") or {}).get("Practice", ["—", ""])
    assert (symbol, detail) == ("✗", "Organization differs")
