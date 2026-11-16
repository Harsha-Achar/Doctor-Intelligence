"""Acceptance checks for patient linking. The matcher does not read the answer key."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from app.patients.db import DB, loads
from app.patients.loader import parse_csv
from app.patients.summaries import DATE_RE

BACKEND = Path(__file__).resolve().parents[2]


def _isolate(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("RUNTIME_DIRECTORY", str(runtime))
    monkeypatch.setenv("ANALYSIS_MODE", "mock")
    monkeypatch.setenv("SMALL_CELL_MIN", "0")
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "false")
    monkeypatch.setenv("AI_SEARCH_ENABLED", "false")
    from app.api import dependencies as deps
    from app.core import settings as settings_mod

    settings_mod.get_settings.cache_clear()

    class TestSettings(settings_mod.Settings):
        @property
        def runtime_path(self):
            return runtime

    monkeypatch.setattr(settings_mod, "Settings", TestSettings)
    settings_mod.get_settings.cache_clear()
    for name in (
        "get_runtime_store",
        "get_repository",
        "get_doctor_service",
        "get_review_service",
        "get_dashboard_service",
    ):
        if hasattr(deps, name):
            getattr(deps, name).cache_clear()
    return runtime


def _clusters():
    with DB() as db:
        rows = db.query(
            """
            SELECT r.source, r.vendor_patient_id, p.daiichi_patient_id, l.layer, s.facts_json, s.text_json, s.model
            FROM pt_link l
            JOIN pt_record r ON r.id = l.record_id
            JOIN pt_patient p ON p.id = l.patient_id
            LEFT JOIN pt_summary s ON s.patient_id = p.id
            WHERE p.retired_into IS NULL
            """
        )
        events = db.query(
            """
            SELECT p.daiichi_patient_id, e.date, e.kind, e.title, e.detail, e.flags_json
            FROM pt_event e JOIN pt_patient p ON p.id = e.patient_id
            """
        )
        reviews = db.query(
            """
            SELECT rv.id, r.source, r.vendor_patient_id, rv.top3_json
            FROM pt_review rv JOIN pt_record r ON r.id = rv.record_id
            WHERE rv.status = 'open'
            """
        )
    by_vendor = {}
    by_patient = defaultdict(list)
    for row in rows:
        by_vendor[(row["source"], row["vendor_patient_id"])] = row
        by_patient[row["daiichi_patient_id"]].append(row)
    by_events = defaultdict(list)
    for row in events:
        by_events[row["daiichi_patient_id"]].append(row)
    return by_vendor, by_patient, by_events, reviews


def _id_of(by_vendor, source, vendor):
    return by_vendor[(source, vendor)]["daiichi_patient_id"]


def _facts(by_vendor, source, vendor):
    return loads(by_vendor[(source, vendor)]["facts_json"], {})


def test_linking_reviews_facts_and_reprocess(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.patients.pipeline import run_pipeline
    from app.patients.service import assign_review
    from app.patients.textutil import parse_iso

    first = run_pipeline("Historical load")
    assert first["patients"] == 30
    assert first["reviews"] == 3

    by_vendor, by_patient, by_events, reviews = _clusters()
    assert len(by_patient) == 30
    assert len(reviews) == 3

    truth = {}
    key_path = BACKEND / "patient-data" / "answer_key" / "patient_answer_key.csv"
    with key_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            truth[(row["source"], row["vendor_patient_id"])] = row
    for members in by_patient.values():
        labels = {truth[(row["source"], row["vendor_patient_id"])]["truth_id"] for row in members}
        assert len(labels) == 1

    members = defaultdict(list)
    for (source, vendor), row in truth.items():
        if row["role"] == "member":
            members[row["truth_id"]].append((source, vendor))

    def layer(source, vendor):
        return by_vendor[(source, vendor)]["layer"]

    for pid in [f"P{n:02d}" for n in list(range(1, 11)) + list(range(27, 31))]:
        hub = next(vendor for source, vendor in members[pid] if source == "hub")
        pharm = next(vendor for source, vendor in members[pid] if source == "pharmacy")
        claim = next(vendor for source, vendor in members[pid] if source == "claims")
        assert layer("hub", hub) == "program_id"
        assert layer("pharmacy", pharm) == "program_id"
        assert layer("claims", claim) == "score"
        assert _id_of(by_vendor, "hub", hub) == _id_of(by_vendor, "claims", claim)

    assert layer("pharmacy", "SPP-2011") == "program_id"
    assert layer("claims", "CV-3011") == "program_id"
    assert layer("hub", "HP-1011") == "program_id"
    assert layer("pharmacy", "SPP-2013") == "score"
    assert _id_of(by_vendor, "hub", "HP-1013") == _id_of(by_vendor, "pharmacy", "SPP-2013")
    assert layer("pharmacy", "SPP-2015") == "score"
    p14 = _id_of(by_vendor, "pharmacy", "SPP-2014")
    assert _id_of(by_vendor, "pharmacy", "SPP-2015") == p14
    switches = [event for event in by_events[p14] if "→" in (event["detail"] or "")]
    assert switches
    assert "Accordia" in switches[0]["detail"]
    assert "Meridian" in switches[0]["detail"]

    assert _id_of(by_vendor, "pharmacy", "SPP-2024") == _id_of(by_vendor, "claims", "CV-3023")
    assert "hub" not in {row["source"] for row in by_patient[_id_of(by_vendor, "pharmacy", "SPP-2024")]}
    assert _facts(by_vendor, "claims", "CV-3024")["status"] == "Claims only"
    assert _id_of(by_vendor, "hub", "HP-1026") != _id_of(by_vendor, "hub", "HP-1027")

    p20 = _facts(by_vendor, "pharmacy", "SPP-2021")
    assert p20["reduction"]["from"] == 3
    assert p20["reduction"]["to"] == 2
    assert any(item["days_late"] == 14 for item in _facts(by_vendor, "pharmacy", "SPP-2022")["delays"])
    assert _facts(by_vendor, "hub", "HP-1023")["status"] == "Stopped"
    assert "side effect" in (_facts(by_vendor, "hub", "HP-1023").get("stop_reason") or "").lower()
    assert _facts(by_vendor, "hub", "HP-1024")["status"] == "Never started"
    assert "denied" in (_facts(by_vendor, "hub", "HP-1024").get("stop_reason") or "").lower()
    assert _facts(by_vendor, "hub", "HP-1025")["status"] == "Waiting to start"
    p29 = _facts(by_vendor, "pharmacy", "SPP-2027")
    assert p29["therapy"]["brand"] == "Brand C"
    assert p29["quantity"] == 60
    titles = " ".join(step["title"].lower() for step in _facts(by_vendor, "hub", "HP-1029")["access"])
    assert "denied" in titles and "appeal" in titles

    for vendor, expected_supply in (("SPP-2021", 21), ("SPP-2022", 21), ("SPP-2027", 30)):
        facts = _facts(by_vendor, "pharmacy", vendor)
        patient_id = _id_of(by_vendor, "pharmacy", vendor)
        doses = [event for event in by_events[patient_id] if event["kind"] == "dose"]
        last = max(doses, key=lambda item: item["date"])
        flags = loads(last["flags_json"], {})
        assert int(flags["days_supply"]) == expected_supply
        assert parse_iso(facts["next_dose"]) == parse_iso(last["date"]) + timedelta(days=expected_supply)

    for row in by_vendor.values():
        text = " ".join(loads(row["text_json"], {}).get("paragraphs") or [])
        facts = loads(row["facts_json"], {})
        blob = json.dumps(facts)
        for label in DATE_RE.findall(text):
            assert label in blob or label in set(facts.get("date_labels") or [])
        assert row["model"] == "template"

    expected_review = {
        ("hub", "HP-1016"): "HP-1015",
        ("claims", "CV-3016"): "HP-1017",
        ("claims", "CV-3017"): "HP-1018",
    }
    assert {(row["source"], row["vendor_patient_id"]) for row in reviews} == set(expected_review)
    ids_before = set(by_patient)
    for row in reviews:
        top = loads(row["top3_json"], [])
        host = expected_review[(row["source"], row["vendor_patient_id"])]
        assert top[0]["daiichi_patient_id"] == _id_of(by_vendor, "hub", host)
    for _ in range(3):
        _by_vendor, _, _, open_reviews = _clusters()
        row = open_reviews[0]
        top = loads(row["top3_json"], [])
        host = expected_review[(row["source"], row["vendor_patient_id"])]
        assert top[0]["daiichi_patient_id"] == _id_of(_by_vendor, "hub", host)
        assign_review(row["id"], top[0]["daiichi_patient_id"])

    by_vendor, by_patient, _, reviews = _clusters()
    assert len(by_patient) == 30
    assert reviews == []
    assert set(by_patient) == ids_before

    second = run_pipeline("Reprocess all")
    by_vendor_2, by_patient_2, _, reviews_2 = _clusters()
    assert second["patients"] == 30
    assert reviews_2 == []
    assert set(by_patient_2) == ids_before
    for key, row in by_vendor.items():
        assert by_vendor_2[key]["daiichi_patient_id"] == row["daiichi_patient_id"]


def test_identifier_column_is_rejected():
    parsed = parse_csv(
        "hub",
        "bad.csv",
        b"first_name,hub_patient_id,event,event_date\nAnn,HP-1,Enrolled,2026-01-01\n",
    )
    assert parsed.rejected
    assert parsed.identifier_ok is False


def test_duplicate_upload_adds_nothing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app.patients.pipeline import run_pipeline

    run_pipeline("Historical load")
    payload = (BACKEND / "patient-data" / "hub_enrollments.csv").read_bytes()
    with DB() as db:
        before = db.one("SELECT COUNT(*) AS n FROM pt_row")["n"]
        files = db.one("SELECT COUNT(*) AS n FROM pt_file")["n"]
    run_pipeline("Upload again", file_payload=payload, file_name="hub_enrollments.csv", file_source="hub")
    with DB() as db:
        assert db.one("SELECT COUNT(*) AS n FROM pt_row")["n"] == before
        assert db.one("SELECT COUNT(*) AS n FROM pt_file")["n"] == files


def test_template_when_azure_is_not_configured(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("ANALYSIS_MODE", "azure")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "")
    from app.core import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    settings = settings_mod.get_settings()
    assert settings.analysis_mode == "azure"
    assert settings.ai_ready is False
    from app.patients.pipeline import run_pipeline

    run_pipeline("Historical load")
    with DB() as db:
        models = {row["model"] for row in db.query("SELECT model FROM pt_summary")}
    assert models == {"template"}
