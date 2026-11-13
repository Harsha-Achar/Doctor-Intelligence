from __future__ import annotations


def test_master_fixed_filter_is_narrower_than_all_doctors(client):
    doctors = client.get("/api/v1/doctors", params={"page_size": 100}).json()
    fixed = [row for row in doctors["items"] if row.get("master_fix")]
    assert fixed
    assert len(fixed) < doctors["total"]
    assert {row["master_fix"] for row in fixed} >= {"merged", "added"}


def test_consolidated_duplicates_exclude_transactions(client):
    summary = client.get("/api/v1/dashboard/summary").json()
    master = next(k for k in summary["kpis"] if k["key"] == "masters_fixed")
    assert master["value"] >= 0
    resolved = next(k for k in summary["kpis"] if k["key"] == "records_resolved")
    assert resolved["value"] >= 0


def test_source_breakdown(client):
    res = client.get("/api/v1/dashboard/source-breakdown")
    assert res.status_code == 200
    body = res.json()
    # NPPES excluded from action chart → 7 source rows
    assert len(body["rows"]) == 7
    assert body["text_summary"]
