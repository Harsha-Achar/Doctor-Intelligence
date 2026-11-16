"""Load files, link records, issue Daiichi IDs, and rebuild journeys."""

from __future__ import annotations

import secrets
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable

from app.patients.config import HISTORICAL_FILES, product_by_brand, patient_data_dir
from app.patients.db import DB, dumps, loads
from app.patients.events import build_events, derive_status
from app.patients.loader import parse_csv
from app.patients.matching import Record, find, finish_layers, groups, layer_program_ids, layer_scores, union
from app.patients.prescriber import lookup_doctor_by_npi
from app.patients.summaries import facts_hash, prepare_facts, write_reasoning, write_summary
from app.patients.textutil import parse_iso

_GUARD = threading.Lock()
_CURRENT: dict[str, int | None] = {"run_id": None}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mode(values: list[Any]) -> Any:
    cleaned = [value for value in values if value not in (None, "")]
    if not cleaned:
        return None
    return Counter(cleaned).most_common(1)[0][0]


def run_pipeline(
    trigger: str,
    *,
    file_payload: bytes | None = None,
    file_name: str | None = None,
    file_source: str | None = None,
    run_id: int | None = None,
) -> dict:
    with _GUARD:
        return _run(trigger, file_payload=file_payload, file_name=file_name, file_source=file_source, run_id=run_id)


def start_pipeline(
    trigger: str,
    *,
    file_payload: bytes | None = None,
    file_name: str | None = None,
    file_source: str | None = None,
) -> int:
    """Start a run and return its id. The work continues on a background thread."""
    with _GUARD:
        if _CURRENT["run_id"]:
            return int(_CURRENT["run_id"])
        with DB() as db:
            run_id = _open_run(db, trigger)
        _CURRENT["run_id"] = run_id

    def worker() -> None:
        try:
            run_pipeline(
                trigger,
                file_payload=file_payload,
                file_name=file_name,
                file_source=file_source,
                run_id=run_id,
            )
        finally:
            with _GUARD:
                if _CURRENT["run_id"] == run_id:
                    _CURRENT["run_id"] = None

    threading.Thread(target=worker, daemon=True).start()
    return run_id


def ensure_ready() -> None:
    with DB() as db:
        empty = db.table_empty("pt_file")
    if empty:
        run_pipeline("Historical load")


def _open_run(db: DB, trigger: str) -> int:
    cursor = db.execute(
        """
        INSERT INTO pt_run (input, rows, new_patients, added_to_existing, review_count, duration, step_log_json, status, started_at)
        VALUES (?, 0, 0, 0, 0, 0, '[]', 'running', ?)
        """,
        (trigger, utc_now()),
    )
    db.commit()
    return int(cursor.lastrowid)


def _log(db: DB, run_id: int, steps: list[dict], title: str, detail: str) -> None:
    steps.append({"at": utc_now(), "title": title, "detail": detail, "status": "done"})
    db.execute("UPDATE pt_run SET step_log_json=? WHERE id=?", (dumps(steps), run_id))
    db.commit()


def _run(
    trigger: str,
    *,
    file_payload: bytes | None,
    file_name: str | None,
    file_source: str | None,
    run_id: int | None,
) -> dict:
    started = datetime.now(timezone.utc)
    with DB() as db:
        if run_id is None:
            run_id = _open_run(db, trigger)
            _CURRENT["run_id"] = run_id
        steps: list[dict] = loads(db.one("SELECT step_log_json FROM pt_run WHERE id=?", (run_id,))["step_log_json"], [])
        try:
            loaded = _load_files(db, file_payload, file_name, file_source)
            _log(db, run_id, steps, "Read and check files", loaded["detail"])
            ident = (
                "Rejected: " + "; ".join(loaded["rejected"])
                if loaded["rejected"]
                else "No names, birth dates, addresses or phone numbers found."
            )
            _log(db, run_id, steps, "Checked for identifiers", ident)
            profiles, vendor_rows = _build_profiles(db)
            _log(
                db,
                run_id,
                steps,
                "Built vendor patient profiles",
                f"{len(profiles)} vendor patient profiles. Prescriber NPIs looked up on the doctor records.",
            )
            result = _match(db, profiles, vendor_rows, steps, run_id)
            _log(
                db,
                run_id,
                steps,
                "Built journeys and summaries",
                f"{result['patients']} patients · {result['reviews']} needs review · summaries refreshed",
            )
            duration = (datetime.now(timezone.utc) - started).total_seconds()
            db.execute(
                """
                UPDATE pt_run
                SET rows=?, new_patients=?, added_to_existing=?, review_count=?, duration=?, status=?, finished_at=?, result_json=?
                WHERE id=?
                """,
                (
                    result["rows"],
                    result["new_patients"],
                    result["added_to_existing"],
                    result["reviews"],
                    duration,
                    "completed",
                    utc_now(),
                    dumps(result),
                    run_id,
                ),
            )
            db.execute(
                "INSERT INTO pt_audit (at, actor, action, details) VALUES (?, ?, ?, ?)",
                (utc_now(), "system", "pipeline", dumps({"run_id": run_id, "trigger": trigger, **result})),
            )
            db.commit()
            result["run_id"] = run_id
            return result
        except Exception as exc:
            db.execute(
                "UPDATE pt_run SET status=?, finished_at=?, result_json=? WHERE id=?",
                ("failed", utc_now(), dumps({"error": str(exc)}), run_id),
            )
            db.commit()
            raise
        finally:
            if _CURRENT["run_id"] == run_id:
                _CURRENT["run_id"] = None


def _load_files(db: DB, payload: bytes | None, name: str | None, source: str | None) -> dict:
    added = 0
    skipped = 0
    held = 0
    rejected: list[str] = []
    targets: list[tuple[str, str, bytes, str]] = []
    if payload is not None:
        targets.append((source or "", name or "upload.csv", payload, "uploaded"))
    else:
        root = patient_data_dir()
        for src, filename in HISTORICAL_FILES:
            path = root / filename
            if path.exists():
                targets.append((src, filename, path.read_bytes(), "historical"))
    for src, filename, body, kind in targets:
        parsed = parse_csv(src, filename, body)
        if parsed.rejected:
            rejected.append(parsed.reject_reason)
            continue
        existing = db.one("SELECT id FROM pt_file WHERE checksum=? AND COALESCE(reject_reason, '')=''", (parsed.checksum,))
        if existing:
            skipped += 1
            continue
        cursor = db.execute(
            """
            INSERT INTO pt_file (source, name, kind, checksum, rows, rows_held_back, period, loaded_at, columns_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.source,
                parsed.name,
                kind,
                parsed.checksum,
                len(parsed.rows_ok) + len(parsed.rows_held),
                len(parsed.rows_held),
                parsed.period,
                utc_now(),
                dumps(parsed.headers),
            ),
        )
        file_id = int(cursor.lastrowid)
        for item in parsed.rows_ok:
            _insert_row(db, file_id, parsed.source, item["raw"], item["parsed"], False, None)
        for item in parsed.rows_held:
            _insert_row(db, file_id, parsed.source, item["raw"], {}, True, item["reason"])
        added += 1
        held += len(parsed.rows_held)
    db.commit()
    detail = f"{added} file(s) loaded, {skipped} already loaded, {held} row(s) held back."
    if rejected:
        detail += " Rejected: " + "; ".join(rejected)
    return {"added": added, "skipped": skipped, "held": held, "rejected": rejected, "detail": detail}


def _insert_row(db: DB, file_id: int, source: str, raw: dict, parsed: dict, held: bool, reason: str | None) -> None:
    db.execute(
        """
        INSERT INTO pt_row (
            file_id, source, raw_json, held_back, hold_reason, vendor_patient_id, event_date,
            birth_year, sex, zip3, prescriber_npi, brand, payer_type, hub_case_id, copay_card_id,
            pharmacy_name, quantity, days_supply, status, product_code, claim_id, claim_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            source,
            dumps(raw),
            1 if held else 0,
            reason,
            parsed.get("vendor_patient_id"),
            parsed.get("event_date"),
            parsed.get("birth_year"),
            parsed.get("sex"),
            parsed.get("zip3"),
            parsed.get("prescriber_npi"),
            parsed.get("brand"),
            parsed.get("payer_type"),
            parsed.get("hub_case_id"),
            parsed.get("copay_card_id"),
            parsed.get("pharmacy_name"),
            parsed.get("quantity"),
            parsed.get("days_supply"),
            parsed.get("status"),
            parsed.get("product_code"),
            parsed.get("claim_id"),
            parsed.get("claim_type"),
        ),
    )


def _build_profiles(db: DB) -> tuple[list[dict], dict[tuple, list[dict]]]:
    rows = db.query(
        """
        SELECT rw.*, f.kind AS file_kind
        FROM pt_row rw
        JOIN pt_file f ON f.id = rw.file_id
        WHERE rw.held_back = 0
        ORDER BY rw.event_date, rw.id
        """
    )
    grouped: dict[tuple, list] = defaultdict(list)
    for row in rows:
        grouped[(row["source"], row["vendor_patient_id"])].append(row)
    existing = {
        (row["source"], row["vendor_patient_id"]): row
        for row in db.query("SELECT * FROM pt_record")
    }
    next_ref = _ref_counters(db)
    profiles = []
    vendor_rows: dict[tuple, list[dict]] = {}
    seen = set()
    npi_cache: dict[str, dict] = {}
    for key, group in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        seen.add(key)
        parsed = [dict(row) for row in group]
        vendor_rows[key] = parsed
        npi = _mode([row["prescriber_npi"] for row in parsed]) or ""
        if npi not in npi_cache:
            npi_cache[npi] = lookup_doctor_by_npi(npi) if npi else {"doctor_id": None, "name": "Unknown prescriber"}
        doctor = npi_cache[npi]
        dates = [row["event_date"] for row in parsed if row["event_date"]]
        pharmacies = []
        for row in parsed:
            if row["pharmacy_name"] and row["pharmacy_name"] not in pharmacies:
                pharmacies.append(row["pharmacy_name"])
        prior = existing.get(key)
        if prior:
            ref = prior["ref"]
            record_id = prior["id"]
            db.execute(
                """
                UPDATE pt_record SET hub_case_ids=?, copay_card_ids=?, birth_year=?, sex=?, zip3=?,
                    prescriber_npi=?, doctor_id=?, prescriber_name=?, brand=?, payer_type=?,
                    pharmacy_names=?, first_date=?, last_date=?, row_count=?, dates_json=?
                WHERE id=?
                """,
                _profile_params(parsed, dates, pharmacies, doctor, npi) + (record_id,),
            )
        else:
            ref = _take_ref(next_ref, key[0])
            cursor = db.execute(
                """
                INSERT INTO pt_record (
                    ref, source, vendor_patient_id, hub_case_ids, copay_card_ids, birth_year, sex, zip3,
                    prescriber_npi, doctor_id, prescriber_name, brand, payer_type, pharmacy_names,
                    first_date, last_date, row_count, dates_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ref, key[0], key[1], *_profile_params(parsed, dates, pharmacies, doctor, npi)),
            )
            record_id = int(cursor.lastrowid)
        profiles.append(_profile_dict(record_id, ref, key, parsed, dates, pharmacies, doctor, npi))
    for key, prior in existing.items():
        if key not in seen:
            db.execute("DELETE FROM pt_record WHERE id=?", (prior["id"],))
    db.commit()
    return profiles, vendor_rows


def _profile_params(parsed, dates, pharmacies, doctor, npi) -> tuple:
    return (
        dumps(sorted({row["hub_case_id"] for row in parsed if row["hub_case_id"]})),
        dumps(sorted({row["copay_card_id"] for row in parsed if row["copay_card_id"]})),
        _mode([row["birth_year"] for row in parsed]),
        _mode([row["sex"] for row in parsed]),
        _mode([row["zip3"] for row in parsed]),
        npi,
        doctor.get("doctor_id"),
        doctor.get("name") or "Unknown prescriber",
        _mode([row["brand"] for row in parsed]),
        _mode([row["payer_type"] for row in parsed]) or "",
        dumps(pharmacies),
        min(dates) if dates else None,
        max(dates) if dates else None,
        len(parsed),
        dumps(dates),
    )


def _profile_dict(record_id, ref, key, parsed, dates, pharmacies, doctor, npi) -> dict:
    return {
        "id": record_id,
        "ref": ref,
        "source": key[0],
        "vendor_patient_id": key[1],
        "hub_case_ids": sorted({row["hub_case_id"] for row in parsed if row["hub_case_id"]}),
        "copay_card_ids": sorted({row["copay_card_id"] for row in parsed if row["copay_card_id"]}),
        "birth_year": _mode([row["birth_year"] for row in parsed]),
        "sex": _mode([row["sex"] for row in parsed]),
        "zip3": _mode([row["zip3"] for row in parsed]),
        "prescriber_npi": npi,
        "doctor_id": doctor.get("doctor_id"),
        "prescriber_name": doctor.get("name") or "Unknown prescriber",
        "brand": _mode([row["brand"] for row in parsed]),
        "payer_type": _mode([row["payer_type"] for row in parsed]) or "",
        "pharmacy_names": pharmacies,
        "dates": [parse_iso(value) for value in dates if parse_iso(value)],
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
        "row_count": len(parsed),
    }


def _ref_counters(db: DB) -> dict[str, int]:
    counters = {"hub": 0, "pharmacy": 0, "claims": 0}
    for row in db.query("SELECT ref FROM pt_record"):
        prefix, _, number = row["ref"].partition("-")
        source = {"HUB": "hub", "SP": "pharmacy", "CLM": "claims"}.get(prefix)
        if source and number.isdigit():
            counters[source] = max(counters[source], int(number))
    return counters


def _take_ref(counters: dict[str, int], source: str) -> str:
    counters[source] += 1
    prefix = {"hub": "HUB", "pharmacy": "SP", "claims": "CLM"}[source]
    return f"{prefix}-{counters[source]:05d}"


def _match(db: DB, profiles: list[dict], vendor_rows: dict, steps: list[dict], run_id: int) -> dict:
    snapshot = _snapshot(db)
    records = {row["id"]: Record(row) for row in profiles}
    by_key = {(row["source"], row["vendor_patient_id"]): records[row["id"]] for row in profiles}
    program_count = layer_program_ids(records)
    _log(db, run_id, steps, "Layer 1 · Program IDs", f"{program_count} records linked on a hub case ID or copay card ID.")
    _log(
        db,
        run_id,
        steps,
        "Layer 2 · Vendor patient IDs",
        f"{len(records)} records, one per vendor patient ID inside each source.",
    )
    reviews = layer_scores(records)
    reviews = {find(records, root): top for root, top in reviews.items()}
    deferred_ids, replayed = _replay(records, reviews, snapshot, by_key)
    review_roots = set(reviews) | {find(records, record_id) for record_id in deferred_ids}
    finish_layers(records, review_roots)
    score_count = sum(1 for record in records.values() if record.layer == "score")
    _log(db, run_id, steps, "Layer 3 · Scoring", f"{score_count} records linked by score. {len(reviews)} sent to review.")

    component_patient, new_patients, added = _assign_ids(db, records, review_roots, snapshot)
    _log(
        db,
        run_id,
        steps,
        "Issued Daiichi patient IDs",
        f"{new_patients} new IDs · {added} records added to an existing patient. Open review records are excluded.",
    )
    _persist_links(db, records, component_patient, review_roots)
    _persist_reviews(db, records, reviews, deferred_ids, component_patient, replayed, profiles)
    reasoning_count = db.one("SELECT COUNT(*) AS n FROM pt_review WHERE status='open'")["n"]
    _log(db, run_id, steps, "Layer 4 · AI evidence check", f"{reasoning_count} low-confidence records explained.")
    _persist_events_and_summaries(db, records, vendor_rows, component_patient, review_roots)
    row_count = db.one("SELECT COUNT(*) AS n FROM pt_row")["n"]
    patients = db.one("SELECT COUNT(*) AS n FROM pt_patient WHERE retired_into IS NULL")["n"]
    return {
        "rows": int(row_count),
        "new_patients": new_patients,
        "added_to_existing": added,
        "reviews": int(reasoning_count),
        "patients": int(patients),
        "updated_patient_ids": sorted(set(component_patient.values())),
    }


def _snapshot(db: DB) -> dict:
    patients = {}
    for row in db.query(
        """
        SELECT r.source, r.vendor_patient_id, p.daiichi_patient_id, p.created_at
        FROM pt_link l
        JOIN pt_record r ON r.id = l.record_id
        JOIN pt_patient p ON p.id = l.patient_id
        WHERE p.retired_into IS NULL
        """
    ):
        patients[(row["source"], row["vendor_patient_id"])] = {
            "daiichi_patient_id": row["daiichi_patient_id"],
            "created_at": row["created_at"],
        }
    reviews = []
    for row in db.query(
        """
        SELECT rv.*, r.source, r.vendor_patient_id
        FROM pt_review rv JOIN pt_record r ON r.id = rv.record_id
        """
    ):
        reviews.append(dict(row))
    return {"patients": patients, "reviews": reviews}


def _replay(records, reviews, snapshot, by_key) -> tuple[set[int], list[dict]]:
    hosts: dict[str, Record] = {}
    for key, info in snapshot["patients"].items():
        record = by_key.get(key)
        if record and info["daiichi_patient_id"] not in hosts:
            hosts[info["daiichi_patient_id"]] = record
    deferred: set[int] = set()
    replayed = []
    for old in snapshot["reviews"]:
        if old["status"] == "open":
            continue
        record = by_key.get((old["source"], old["vendor_patient_id"]))
        if record is None:
            continue
        root = find(records, record.id)
        reviews.pop(root, None)
        if old["status"] == "assigned" and old.get("target_patient_id"):
            host = hosts.get(old["target_patient_id"])
            if host is not None:
                union(records, host.id, record.id)
                record.layer = "reviewer"
                record.reason = "Assigned by reviewer"
                record.score_items = loads(old.get("top3_json"), [])
        elif old["status"] == "new_patient":
            record.layer = "reviewer"
            record.reason = "Created as a new patient by reviewer"
        elif old["status"] == "deferred":
            deferred.add(record.id)
        replayed.append(old)
    # Re-key reviews after unions performed above.
    moved: dict[int, list] = {}
    for root, top in list(reviews.items()):
        moved.setdefault(find(records, root), top)
    reviews.clear()
    reviews.update(moved)
    return deferred, replayed


def _assign_ids(db: DB, records, review_roots: set[int], snapshot: dict) -> tuple[dict[int, str], int, int]:
    existing_ids = {row["daiichi_patient_id"] for row in db.query("SELECT daiichi_patient_id FROM pt_patient")}
    created_at = {row["daiichi_patient_id"]: row["created_at"] for row in db.query("SELECT daiichi_patient_id, created_at FROM pt_patient")}
    component_patient: dict[int, str] = {}
    new_patients = 0
    added = 0
    for root, members in groups(records).items():
        if root in review_roots:
            continue
        prior = []
        for member in members:
            info = snapshot["patients"].get((member.source, member.vendor_patient_id))
            if info:
                prior.append(info)
        prior.sort(key=lambda item: item["created_at"])
        if prior:
            chosen = prior[0]["daiichi_patient_id"]
            extras = []
            seen = {chosen}
            for item in prior[1:]:
                if item["daiichi_patient_id"] not in seen:
                    seen.add(item["daiichi_patient_id"])
                    extras.append(item["daiichi_patient_id"])
            for retired in extras:
                db.execute(
                    "UPDATE pt_patient SET retired_into=? WHERE daiichi_patient_id=? AND retired_into IS NULL",
                    (chosen, retired),
                )
            added += sum(1 for member in members if (member.source, member.vendor_patient_id) not in snapshot["patients"])
        else:
            chosen = _new_dsp(existing_ids)
            created_at[chosen] = utc_now()
            db.execute(
                "INSERT INTO pt_patient (daiichi_patient_id, created_at) VALUES (?, ?)",
                (chosen, created_at[chosen]),
            )
            new_patients += 1
        if chosen not in created_at:
            created_at[chosen] = utc_now()
            db.execute(
                "INSERT INTO pt_patient (daiichi_patient_id, created_at) VALUES (?, ?)",
                (chosen, created_at[chosen]),
            )
        component_patient[root] = chosen
    db.execute("DELETE FROM pt_link")
    db.commit()
    return component_patient, new_patients, added


def _new_dsp(existing: set[str]) -> str:
    while True:
        value = "DSP-" + secrets.token_hex(4)[:7].upper()
        if value not in existing:
            existing.add(value)
            return value


def _persist_links(db: DB, records, component_patient: dict[int, str], review_roots: set[int]) -> None:
    now = utc_now()
    for record in records.values():
        root = find(records, record.id)
        if root in review_roots:
            continue
        daiichi = component_patient[root]
        patient = db.one("SELECT id FROM pt_patient WHERE daiichi_patient_id=?", (daiichi,))
        db.execute(
            """
            INSERT INTO pt_link (record_id, patient_id, layer, reason, score, score_items_json, decided_by, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                patient["id"],
                record.layer or "first_record",
                record.reason,
                record.score,
                dumps(record.score_items) if record.score_items else None,
                "reviewer" if record.layer == "reviewer" else "system",
                now,
            ),
        )
    db.commit()


def _persist_reviews(db, records, reviews, deferred_ids, component_patient, replayed, profiles) -> None:
    db.execute("DELETE FROM pt_review")
    profile_by_id = {row["id"]: row for row in profiles}
    for root, top in reviews.items():
        members = [record for record in records.values() if find(records, record.id) == root]
        if not members:
            continue
        record = sorted(members, key=lambda item: item.ref)[0]
        top3 = []
        for candidate in top:
            cand_root = find(records, candidate["root"])
            top3.append(
                {
                    "daiichi_patient_id": component_patient.get(cand_root),
                    "score": candidate["score"],
                    "items": candidate["items"],
                    "probability": 1 / (1 + 2 ** (-(candidate["score"] - 6) / 1.5)),
                }
            )
        payload = _reasoning_facts(record, profile_by_id.get(record.id, {}), top3)
        reasoning = write_reasoning(payload)
        db.execute(
            """
            INSERT INTO pt_review (record_id, top3_json, ai_reasoning_json, status)
            VALUES (?, ?, ?, 'open')
            """,
            (record.id, dumps(top3), dumps(reasoning)),
        )
    for record_id in deferred_ids:
        db.execute(
            "INSERT INTO pt_review (record_id, top3_json, ai_reasoning_json, status) VALUES (?, '[]', ?, 'deferred')",
            (record_id, dumps({"template": True, "recommendation": "Deferred."})),
        )
    for old in replayed:
        if old["status"] not in {"assigned", "new_patient"}:
            continue
        record = db.one(
            "SELECT id FROM pt_record WHERE source=? AND vendor_patient_id=?",
            (old["source"], old["vendor_patient_id"]),
        )
        if record is None:
            continue
        db.execute(
            """
            INSERT INTO pt_review (record_id, top3_json, ai_reasoning_json, status, resolved_by, resolved_at, target_patient_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                old.get("top3_json") or "[]",
                old.get("ai_reasoning_json") or "{}",
                old["status"],
                old.get("resolved_by"),
                old.get("resolved_at"),
                old.get("target_patient_id"),
            ),
        )
    db.commit()


def _reasoning_facts(record: Record, profile: dict, top3: list[dict]) -> dict:
    dates = [item.isoformat() for item in record.dates]
    return {
        "record_ref": record.ref,
        "source": record.source,
        "birth_year": record.birth_year,
        "sex": record.sex,
        "zip3": record.zip3,
        "prescriber": record.prescriber_name,
        "brand": record.brand,
        "payer_type": record.payer_type,
        "dates": dates,
        "candidates": [
            {
                "patient_id": item.get("daiichi_patient_id"),
                "score": item.get("score"),
                "items": item.get("items"),
                "suggested": index == 0 and (len(top3) == 1 or item["score"] - top3[1]["score"] >= 3),
                "margin": (item["score"] - top3[1]["score"]) if index == 0 and len(top3) > 1 else (None if len(top3) < 2 else None),
            }
            for index, item in enumerate(top3)
        ],
        "why_not_auto": "The best score is under +10, or it does not lead the next candidate by 3 points.",
        "profile_ref": profile.get("ref"),
    }


def _persist_events_and_summaries(db, records, vendor_rows, component_patient, review_roots) -> None:
    db.execute("DELETE FROM pt_event")
    as_of_row = db.one("SELECT MAX(event_date) AS d FROM pt_row WHERE held_back=0")
    as_of = as_of_row["d"] if as_of_row else None
    pending_by_patient = defaultdict(int)
    for root, _top in []:
        pass
    open_reviews = db.query(
        """
        SELECT rv.top3_json FROM pt_review rv WHERE rv.status='open'
        """
    )
    for row in open_reviews:
        for candidate in loads(row["top3_json"], []):
            if candidate.get("daiichi_patient_id"):
                pending_by_patient[candidate["daiichi_patient_id"]] += 1
    for root, members in groups(records).items():
        if root in review_roots or root not in component_patient:
            continue
        daiichi = component_patient[root]
        patient = db.one("SELECT id, created_at FROM pt_patient WHERE daiichi_patient_id=?", (daiichi,))
        record_dicts = []
        rows_by_record = {}
        for member in members:
            record_dicts.append(
                {
                    "id": member.id,
                    "ref": member.ref,
                    "source": member.source,
                    "vendor_patient_id": member.vendor_patient_id,
                    "brand": member.brand,
                    "first_date": member.dates[0].isoformat() if member.dates else None,
                }
            )
            rows_by_record[member.id] = vendor_rows.get((member.source, member.vendor_patient_id), [])
        # first_date on the dict should be the earliest date.
        for item in record_dicts:
            dates = vendor_rows.get((item["source"], item["vendor_patient_id"]), [])
            dated = [row["event_date"] for row in dates if row.get("event_date")]
            item["first_date"] = min(dated) if dated else None
        events = build_events(record_dicts, rows_by_record)
        for event in events:
            db.execute(
                """
                INSERT INTO pt_event (patient_id, date, source, record_id, kind, title, detail, quantity, pharmacy, flags_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patient["id"],
                    event["date"],
                    event["source"],
                    event["record_id"],
                    event["kind"],
                    event["title"],
                    event["detail"],
                    event["quantity"],
                    event["pharmacy"],
                    dumps(event["flags"]),
                ),
            )
        sources = {member.source for member in members}
        derived = derive_status(events, sources)
        anchor = sorted(members, key=lambda item: (item.dates[0] if item.dates else datetime.max.date(), item.ref))[0]
        facts = _facts(daiichi, anchor, members, derived, events, as_of, pending_by_patient[daiichi])
        facts = prepare_facts(facts)
        digest = facts_hash(facts)
        current = db.one("SELECT facts_hash, text_json, model FROM pt_summary WHERE patient_id=?", (patient["id"],))
        if current and current["facts_hash"] == digest:
            continue
        text, model = write_summary(facts)
        if current:
            db.execute(
                "UPDATE pt_summary SET facts_json=?, text_json=?, facts_hash=?, model=?, generated_at=? WHERE patient_id=?",
                (dumps(facts), dumps(text), digest, model, utc_now(), patient["id"]),
            )
        else:
            db.execute(
                """
                INSERT INTO pt_summary (patient_id, facts_json, text_json, facts_hash, model, generated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (patient["id"], dumps(facts), dumps(text), digest, model, utc_now()),
            )
    db.execute("DELETE FROM pt_summary WHERE patient_id NOT IN (SELECT DISTINCT patient_id FROM pt_link)")
    db.execute("DELETE FROM pt_event WHERE patient_id NOT IN (SELECT DISTINCT patient_id FROM pt_link)")
    db.execute(
        "DELETE FROM pt_patient WHERE retired_into IS NULL AND id NOT IN (SELECT DISTINCT patient_id FROM pt_link)"
    )
    db.commit()


def _facts(daiichi, anchor: Record, members: list[Record], derived: dict, events: list[dict], as_of: str | None, pending: int) -> dict:
    product = product_by_brand(anchor.brand or "") or {}
    access = [{"title": event["title"], "date": event["date"]} for event in events if event["kind"] == "access" or (event["kind"] == "stop" and event["source"] == "hub")]
    delays = []
    reduction = None
    switch_date = None
    for event in events:
        flags = event.get("flags") or {}
        if event["kind"] == "note" and flags.get("days_late"):
            delays.append({"date": event["date"], "days_late": flags["days_late"]})
        if event["kind"] == "note" and flags.get("reduced_from") is not None and reduction is None:
            reduction = {"from": flags["reduced_from"], "to": flags.get("reduced_to"), "date": event["date"]}
        if flags.get("switch"):
            switch_date = event["date"]
    sources = {member.source for member in members}
    watch = []
    if derived["status"] == "On therapy" and derived.get("first_dose") and derived.get("last_dose"):
        first = parse_iso(derived["first_dose"])
        last = parse_iso(derived["last_dose"])
        if first and last and (last - first).days > 300:
            watch.append("prior authorization renewal likely due")
    if derived["dose_count"] and "claims" not in sources:
        watch.append("no claims linked")
    if derived["dose_count"] and "hub" not in sources:
        watch.append("treated outside the hub")
    if pending:
        watch.append("records pending review")
    return {
        "patient_id": daiichi,
        "status": derived["status"],
        "therapy": {
            "brand": anchor.brand,
            "description": product.get("description"),
            "unit": product.get("unit"),
            "cycle_days": product.get("cycle_days"),
        },
        "as_of": as_of,
        "first_dose": derived.get("first_dose"),
        "last_dose": derived.get("last_dose"),
        "next_dose": derived.get("next_dose"),
        "overdue": bool(derived.get("next_dose") and as_of and derived["next_dose"] < as_of),
        "dose_count": derived["dose_count"],
        "quantity": derived.get("current_quantity"),
        "reduction": reduction,
        "delays": delays,
        "pharmacy": derived.get("pharmacy"),
        "previous_pharmacy": derived.get("previous_pharmacy") if derived.get("switched") else None,
        "switch_date": switch_date,
        "access": access,
        "stop_reason": derived.get("stop_reason") if derived["status"] in {"Stopped", "Never started"} else None,
        "stop_date": derived.get("stop_date"),
        "watch": watch,
        "record_refs": [member.ref for member in sorted(members, key=lambda item: item.ref)],
        "birth_year": anchor.birth_year,
        "sex": anchor.sex,
        "zip3": anchor.zip3,
        "prescriber": anchor.prescriber_name,
        "payer_type": anchor.payer_type,
    }
