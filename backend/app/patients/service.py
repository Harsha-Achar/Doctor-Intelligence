"""Read models and reviewer decisions for the patient API."""

from __future__ import annotations

import uuid
from collections import defaultdict

from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.settings import get_settings
from app.patients.analytics import journey_analytics
from app.patients.config import (
    AUTO_MIN,
    MARGIN,
    PRODUCTS,
    REVIEW_MIN,
    SOURCE_BLURB,
    SOURCE_LABELS,
    small_cell_min,
)
from app.patients.db import DB, dumps, loads
from app.patients.evaluate import quality
from app.patients.loader import parse_csv
from app.patients.pipeline import run_pipeline, start_pipeline, utc_now
from app.patients.textutil import age_band, age_band_short, fmt_date

AUTO_LAYERS = {"program_id", "vendor_id", "score"}
LAYER_META = [
    ("program_id", "Layer 1", "Hub case ID or copay card ID shared across sources", "A pharmacy referral carries the same hub case ID as the hub enrollment"),
    ("vendor_id", "Layer 2", "Same patient ID inside one vendor's data", "Two claims for the same claims-vendor patient ID"),
    ("score", "Layer 3", "Scored on birth year, sex, ZIP3, prescriber, product, payer and dates", "A claim within 4 days of a pharmacy fill, same prescriber, birth year, ZIP3 and product"),
    ("reviewer", "Layer 4", "Low-confidence record assigned by a Daiichi user", "A data steward picked the right patient from the 3 nearest"),
    ("needs_review", "Waiting", "Nearest patients found, not confident enough to link", "Shown in Needs review with the 3 nearest patients"),
    ("first_record", "No match", "No other record for this person yet", "A hub enrollment with no therapy yet"),
]


def _sex(value: str | None) -> str:
    if value == "F":
        return "Female"
    if value == "M":
        return "Male"
    return value or ""


def _as_of(db: DB) -> str | None:
    row = db.one("SELECT MAX(event_date) AS d FROM pt_row WHERE held_back=0")
    return row["d"] if row else None


def overview() -> dict:
    with DB() as db:
        rows = db.one("SELECT COUNT(*) AS n FROM pt_row")["n"]
        files = db.one("SELECT COUNT(*) AS n FROM pt_file")["n"]
        patients = db.one("SELECT COUNT(*) AS n FROM pt_patient WHERE retired_into IS NULL")["n"]
        reviews = db.one("SELECT COUNT(*) AS n FROM pt_review WHERE status IN ('open', 'deferred')")["n"]
        total = db.one("SELECT COUNT(*) AS n FROM pt_record")["n"]
        auto = db.one(
            "SELECT COUNT(*) AS n FROM pt_link WHERE layer IN ('program_id', 'vendor_id', 'score')"
        )["n"]
        as_of = _as_of(db)
    return {
        "rows_processed": int(rows),
        "files": int(files),
        "patients": int(patients),
        "mapped_automatically_pct": round(100 * auto / total) if total else 0,
        "mapped_automatically": int(auto),
        "records": int(total),
        "needs_review": int(reviews),
        "as_of": as_of,
        "as_of_label": fmt_date(as_of),
        "brands": [{"brand": item["brand"], "description": item["description"]} for item in PRODUCTS],
        "small_cell_min": small_cell_min(),
    }


def mapping() -> dict:
    with DB() as db:
        links = db.query("SELECT layer, COUNT(*) AS n FROM pt_link GROUP BY layer")
        record_count = int(db.one("SELECT COUNT(*) AS n FROM pt_record")["n"])
        divisor = record_count or 1
        open_reviews = db.one("SELECT COUNT(*) AS n FROM pt_review WHERE status IN ('open', 'deferred')")["n"]
        examples = {}
        for row in db.query(
            """
            SELECT l.layer, r.ref, l.reason FROM pt_link l
            JOIN pt_record r ON r.id = l.record_id
            """
        ):
            examples.setdefault(row["layer"], f"{row['ref']} · {row['reason']}")
    counts = {row["layer"]: row["n"] for row in links}
    counts["needs_review"] = int(open_reviews)
    layers = []
    for key, title, description, example in LAYER_META:
        count = int(counts.get(key, 0))
        layers.append(
            {
                "layer": key,
                "title": title,
                "description": description,
                "example": examples.get(key) or example,
                "count": count,
                "pct": round(100 * count / divisor) if record_count else 0,
            }
        )
    report = quality()
    quality_line = None
    if report is not None:
        wrong = int(report["wrong_merges"])
        pct = report.get("link_correct_pct", 100)
        pct_text = f"{pct:g}"
        id_word = "patient ID" if wrong == 1 else "patient IDs"
        quality_line = (
            f"Quality check on the synthetic answer key: {pct_text}% of links are correct"
            f" · {wrong} {id_word} with a wrong merge."
        )
    return {"records": record_count, "layers": layers, "quality": report, "quality_line": quality_line}


def mapping_records(layer: str) -> dict:
    with DB() as db:
        if layer == "needs_review":
            rows = db.query(
                """
                SELECT r.ref, r.source, r.vendor_patient_id, 'Needs review' AS reason, NULL AS daiichi_patient_id
                FROM pt_review rv JOIN pt_record r ON r.id = rv.record_id
                WHERE rv.status IN ('open', 'deferred')
                ORDER BY r.ref
                """
            )
        else:
            rows = db.query(
                """
                SELECT r.ref, r.source, r.vendor_patient_id, l.reason, p.daiichi_patient_id
                FROM pt_link l
                JOIN pt_record r ON r.id = l.record_id
                JOIN pt_patient p ON p.id = l.patient_id
                WHERE l.layer = ?
                ORDER BY r.ref
                """,
                (layer,),
            )
    return {
        "layer": layer,
        "records": [
            {
                "ref": row["ref"],
                "source": row["source"],
                "source_label": SOURCE_LABELS.get(row["source"], row["source"]),
                "reason": row["reason"],
                "daiichi_patient_id": row["daiichi_patient_id"],
            }
            for row in rows
        ],
    }


def sources() -> dict:
    with DB() as db:
        files = db.query("SELECT * FROM pt_file ORDER BY id")
        by_source: dict[str, list] = defaultdict(list)
        for row in files:
            by_source[row["source"]].append(row)
        cards = []
        for source in ("hub", "pharmacy", "claims"):
            group = by_source.get(source, [])
            record_rows = db.query("SELECT id FROM pt_record WHERE source=?", (source,))
            linked = db.query(
                """
                SELECT r.id FROM pt_record r
                JOIN pt_link l ON l.record_id = r.id
                WHERE r.source = ?
                """,
                (source,),
            )
            vendor = db.one("SELECT COUNT(DISTINCT vendor_patient_id) AS n FROM pt_record WHERE source=?", (source,))["n"]
            row_count = sum(int(item["rows"] or 0) for item in group)
            total = len(record_rows) or 0
            cards.append(
                {
                    "source": source,
                    "label": SOURCE_LABELS[source],
                    "description": SOURCE_BLURB[source],
                    "rows": row_count,
                    "vendor_patients": int(vendor),
                    "mapped_pct": round(100 * len(linked) / total) if total else 0,
                    "files": [
                        {
                            "id": item["id"],
                            "name": item["name"],
                            "kind": item["kind"],
                            "period": item["period"],
                            "rows": item["rows"],
                            "rows_held_back": item["rows_held_back"],
                            "loaded_at": item["loaded_at"],
                        }
                        for item in group
                    ],
                }
            )
    return {"sources": cards}


def file_detail(file_id: int) -> dict:
    with DB() as db:
        file_row = db.one("SELECT * FROM pt_file WHERE id=?", (file_id,))
        if file_row is None:
            raise NotFoundError("File not found.")
        sample = db.query(
            "SELECT raw_json, held_back, hold_reason FROM pt_row WHERE file_id=? ORDER BY id LIMIT 20",
            (file_id,),
        )
    with DB() as db:
        vendor_patients = db.one(
            "SELECT COUNT(DISTINCT vendor_patient_id) AS n FROM pt_row WHERE file_id=? AND held_back=0",
            (file_id,),
        )["n"]
    return {
        "id": file_row["id"],
        "name": file_row["name"],
        "source": file_row["source"],
        "kind": file_row["kind"],
        "period": file_row["period"],
        "row_count": file_row["rows"],
        "vendor_patients": int(vendor_patients),
        "columns": loads(file_row["columns_json"], []),
        "rows_held_back": file_row["rows_held_back"],
        "rows": [
            {"values": loads(row["raw_json"], {}), "held_back": bool(row["held_back"]), "reason": row["hold_reason"]}
            for row in sample
        ],
    }


def runs() -> dict:
    with DB() as db:
        rows = db.query("SELECT * FROM pt_run ORDER BY id DESC")
    return {"runs": [_run_row(row) for row in rows]}


def run_detail(run_id: int) -> dict:
    with DB() as db:
        row = db.one("SELECT * FROM pt_run WHERE id=?", (run_id,))
    if row is None:
        raise NotFoundError("Run not found.")
    return _run_row(row, steps=True)


def _run_row(row, steps: bool = False) -> dict:
    payload = {
        "id": row["id"],
        "input": row["input"],
        "rows": row["rows"],
        "new_patients": row["new_patients"],
        "added_to_existing": row["added_to_existing"],
        "review_count": row["review_count"],
        "duration": row["duration"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "result": loads(row["result_json"], {}),
    }
    if steps:
        payload["steps"] = loads(row["step_log_json"], [])
    return payload


def reprocess() -> dict:
    run_id = start_pipeline("Reprocess all")
    return {"run_id": run_id}


def preview_upload(source: str, filename: str, payload: bytes) -> dict:
    parsed = parse_csv(source, filename, payload)
    upload_id = uuid.uuid4().hex[:12]
    folder = get_settings().runtime_path / "patient_uploads"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{upload_id}.bin").write_bytes(payload)
    (folder / f"{upload_id}.json").write_text(
        dumps({"source": source, "filename": filename}),
        encoding="utf-8",
    )
    preview_rows = []
    for item in (parsed.rows_ok[:5] if not parsed.rejected else []):
        preview_rows.append(item["raw"])
    return {
        "upload_id": upload_id,
        "source": source,
        "filename": filename,
        "rejected": parsed.rejected,
        "reject_reason": parsed.reject_reason,
        "identifier_ok": parsed.identifier_ok,
        "identifier_message": parsed.identifier_message,
        "rows": len(parsed.rows_ok),
        "rows_held_back": len(parsed.rows_held),
        "mapping": parsed.mapping,
        "preview_rows": preview_rows,
        "headers": parsed.headers,
    }


def process_upload(upload_id: str) -> dict:
    folder = get_settings().runtime_path / "patient_uploads"
    meta_path = folder / f"{upload_id}.json"
    data_path = folder / f"{upload_id}.bin"
    if not meta_path.exists() or not data_path.exists():
        raise NotFoundError("Upload not found.")
    meta = loads(meta_path.read_text(encoding="utf-8"), {})
    payload = data_path.read_bytes()
    parsed = parse_csv(meta["source"], meta["filename"], payload)
    if parsed.rejected:
        raise ValidationAppError(parsed.reject_reason or "The file was rejected.")
    run_id = start_pipeline(
        f"Upload {meta['filename']}",
        file_payload=payload,
        file_name=meta["filename"],
        file_source=meta["source"],
    )
    return {"run_id": run_id}


def _patient_bundle(db: DB, daiichi: str) -> dict | None:
    patient = db.one(
        "SELECT * FROM pt_patient WHERE daiichi_patient_id=? AND retired_into IS NULL",
        (daiichi,),
    )
    if patient is None:
        retired = db.one("SELECT retired_into FROM pt_patient WHERE daiichi_patient_id=?", (daiichi,))
        if retired and retired["retired_into"]:
            raise NotFoundError(f"{daiichi} was merged into {retired['retired_into']}.")
        return None
    summary = db.one("SELECT * FROM pt_summary WHERE patient_id=?", (patient["id"],))
    links = db.query(
        """
        SELECT l.layer, l.reason, l.score, l.score_items_json, l.decided_by, l.decided_at,
               r.id AS record_id, r.ref, r.source, r.vendor_patient_id, r.hub_case_ids, r.copay_card_ids,
               r.birth_year, r.sex, r.zip3, r.prescriber_npi, r.doctor_id, r.prescriber_name,
               r.brand, r.payer_type, r.pharmacy_names, r.first_date, r.last_date, r.row_count
        FROM pt_link l JOIN pt_record r ON r.id = l.record_id
        WHERE l.patient_id=?
        ORDER BY r.first_date, r.ref
        """,
        (patient["id"],),
    )
    events = db.query("SELECT * FROM pt_event WHERE patient_id=? ORDER BY date, id", (patient["id"],))
    return {"patient": patient, "summary": summary, "links": links, "events": events}


def list_patients(
    *,
    status: str | None = None,
    switched: bool | None = None,
    pending: bool | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValidationAppError("page must be >= 1 and page_size between 1 and 100.")
    with DB() as db:
        as_of = _as_of(db)
        rows = db.query(
            """
            SELECT p.daiichi_patient_id, s.facts_json
            FROM pt_patient p
            LEFT JOIN pt_summary s ON s.patient_id = p.id
            WHERE p.retired_into IS NULL
            """
        )
        vendor = db.query(
            """
            SELECT p.daiichi_patient_id, r.vendor_patient_id, r.source
            FROM pt_link l
            JOIN pt_patient p ON p.id = l.patient_id
            JOIN pt_record r ON r.id = l.record_id
            """
        )
        open_top = []
        for review in db.query("SELECT top3_json FROM pt_review WHERE status IN ('open', 'deferred')"):
            for item in loads(review["top3_json"], []):
                if item.get("daiichi_patient_id"):
                    open_top.append(item["daiichi_patient_id"])
    vendors: dict[str, list[str]] = defaultdict(list)
    sources: dict[str, set[str]] = defaultdict(set)
    for row in vendor:
        vendors[row["daiichi_patient_id"]].append(row["vendor_patient_id"])
        sources[row["daiichi_patient_id"]].add(row["source"])
    pending_ids = set(open_top)
    items = []
    for row in rows:
        facts = loads(row["facts_json"], {}) or {}
        daiichi = row["daiichi_patient_id"]
        item_status = facts.get("status") or ""
        is_switched = bool(facts.get("previous_pharmacy") or facts.get("switch_date"))
        is_pending = daiichi in pending_ids
        if status and item_status != status:
            continue
        if switched and not is_switched:
            continue
        if pending and not is_pending:
            continue
        needle = (q or "").strip().lower()
        if needle and needle not in daiichi.lower() and not any(needle in value.lower() for value in vendors.get(daiichi, [])):
            continue
        therapy = facts.get("therapy") or {}
        items.append(
            {
                "daiichi_patient_id": daiichi,
                "age_band": age_band_short(facts.get("birth_year"), parse_as_of(as_of)),
                "age_band_range": age_band(facts.get("birth_year"), parse_as_of(as_of)),
                "sex": _sex(facts.get("sex")),
                "payer_type": facts.get("payer_type"),
                "brand": therapy.get("brand"),
                "description": therapy.get("description"),
                "status": item_status,
                "next_dose": facts.get("next_dose"),
                "next_dose_label": fmt_date(facts.get("next_dose")),
                "overdue": bool(facts.get("overdue")),
                "stop_date": facts.get("stop_date"),
                "stop_date_label": fmt_date(facts.get("stop_date")),
                "prescriber": facts.get("prescriber"),
                "doctor_id": None,
                "pharmacy": facts.get("pharmacy"),
                "switched": is_switched,
                "previous_pharmacy": facts.get("previous_pharmacy"),
                "sources": sorted(sources.get(daiichi, [])),
                "pending": is_pending,
            }
        )
    # doctor ids need a real lookup. Fill them in a second query below if missing.
    items = _attach_doctors(items)
    items.sort(key=lambda item: item.get("next_dose") or item.get("stop_date") or "", reverse=True)
    total = len(items)
    start = (page - 1) * page_size
    counts = _filter_counts(rows, pending_ids)
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "as_of": as_of,
        "as_of_label": fmt_date(as_of),
        "counts": counts,
        "mapped_automatically_pct": overview()["mapped_automatically_pct"],
    }


def parse_as_of(value):
    from app.patients.textutil import parse_iso

    return parse_iso(value)


def _attach_doctors(items: list[dict]) -> list[dict]:
    if not items:
        return items
    with DB() as db:
        rows = db.query(
            """
            SELECT p.daiichi_patient_id, r.doctor_id, r.prescriber_name
            FROM pt_link l
            JOIN pt_patient p ON p.id = l.patient_id
            JOIN pt_record r ON r.id = l.record_id
            WHERE r.doctor_id IS NOT NULL
            """
        )
    found = {}
    for row in rows:
        found.setdefault(row["daiichi_patient_id"], row["doctor_id"])
    for item in items:
        item["doctor_id"] = found.get(item["daiichi_patient_id"])
    return items


def _filter_counts(rows, pending_ids) -> dict:
    counts = {
        "all": 0,
        "On therapy": 0,
        "Waiting to start": 0,
        "Stopped": 0,
        "Never started": 0,
        "Claims only": 0,
        "switched": 0,
        "pending": 0,
    }
    for row in rows:
        facts = loads(row["facts_json"], {}) or {}
        counts["all"] += 1
        status = facts.get("status")
        if status in counts:
            counts[status] += 1
        if facts.get("previous_pharmacy") or facts.get("switch_date"):
            counts["switched"] += 1
        if row["daiichi_patient_id"] in pending_ids:
            counts["pending"] += 1
    return counts


def patient_detail(daiichi: str) -> dict:
    with DB() as db:
        bundle = _patient_bundle(db, daiichi)
        if bundle is None:
            raise NotFoundError("Patient not found.")
        as_of = _as_of(db)
        pending = _pending_refs(db, daiichi)
    facts = loads(bundle["summary"]["facts_json"], {}) if bundle["summary"] else {}
    text = loads(bundle["summary"]["text_json"], {}) if bundle["summary"] else {}
    links = bundle["links"]
    anchor = links[0] if links else {}
    therapy = facts.get("therapy") or {}
    return {
        "daiichi_patient_id": daiichi,
        "status": facts.get("status"),
        "brand": therapy.get("brand") or anchor.get("brand"),
        "description": therapy.get("description"),
        "age_band": age_band(facts.get("birth_year") or anchor.get("birth_year"), parse_as_of(as_of)),
        "sex": _sex(facts.get("sex") or anchor.get("sex")),
        "payer_type": facts.get("payer_type") or anchor.get("payer_type"),
        "prescriber": facts.get("prescriber") or anchor.get("prescriber_name"),
        "doctor_id": next((link["doctor_id"] for link in links if link["doctor_id"]), None),
        "sources": sorted({link["source"] for link in links}),
        "no_identity": True,
        "record_count": len(links),
        "pending_reviews": pending,
        "as_of": as_of,
        "as_of_label": fmt_date(as_of),
        "kpis": {
            "next_dose": facts.get("next_dose"),
            "next_dose_label": fmt_date(facts.get("next_dose")),
            "overdue": bool(facts.get("overdue")),
            "stop_date": facts.get("stop_date"),
            "stop_date_label": fmt_date(facts.get("stop_date")),
            "stop_reason": facts.get("stop_reason"),
            "current_quantity": facts.get("quantity"),
            "unit": therapy.get("unit"),
            "dose_count": facts.get("dose_count"),
            "first_dose": facts.get("first_dose"),
            "first_dose_label": fmt_date(facts.get("first_dose")),
            "pharmacy": facts.get("pharmacy"),
            "previous_pharmacy": facts.get("previous_pharmacy"),
            "switch_date_label": fmt_date(facts.get("switch_date")),
        },
        "summary": {
            "paragraphs": text.get("paragraphs") or [],
            "template": bool(text.get("template", True)),
            "model": bundle["summary"]["model"] if bundle["summary"] else "template",
        },
        "facts": facts,
    }


def _pending_refs(db: DB, daiichi: str) -> list[dict]:
    found = []
    for review in db.query(
        """
        SELECT rv.id, r.ref, rv.top3_json FROM pt_review rv
        JOIN pt_record r ON r.id = rv.record_id
        WHERE rv.status IN ('open', 'deferred')
        """
    ):
        for item in loads(review["top3_json"], []):
            if item.get("daiichi_patient_id") == daiichi:
                found.append({"review_id": review["id"], "ref": review["ref"]})
                break
    return found


def patient_timeline(daiichi: str) -> dict:
    with DB() as db:
        bundle = _require(db, daiichi)
    events = []
    for row in bundle["events"]:
        flags = loads(row["flags_json"], {})
        ref = _ref_for(bundle, row["record_id"])
        events.append(
            {
                "date": row["date"],
                "date_label": fmt_date(row["date"]),
                "source": row["source"],
                "source_label": SOURCE_LABELS.get(row["source"], row["source"]),
                "kind": row["kind"],
                "title": row["title"],
                "detail": row["detail"],
                "quantity": row["quantity"],
                "pharmacy": row["pharmacy"],
                "flags": flags,
                "ref": ref,
                "record_id": row["record_id"],
            }
        )
    return {"daiichi_patient_id": daiichi, "events": events}


def patient_doses(daiichi: str) -> dict:
    timeline = patient_timeline(daiichi)
    detail = patient_detail(daiichi)
    doses = [event for event in timeline["events"] if event["kind"] == "dose"]
    return {
        "daiichi_patient_id": daiichi,
        "doses": doses,
        "next_dose": detail["kpis"]["next_dose"],
        "next_dose_label": detail["kpis"]["next_dose_label"],
        "unit": detail["kpis"]["unit"],
    }


def patient_records(daiichi: str) -> dict:
    with DB() as db:
        bundle = _require(db, daiichi)
        similar = _similar(db, bundle)
    records = []
    for link in bundle["links"]:
        records.append(
            {
                "ref": link["ref"],
                "source": link["source"],
                "source_label": SOURCE_LABELS.get(link["source"], link["source"]),
                "vendor_patient_id": link["vendor_patient_id"],
                "layer": link["layer"],
                "reason": link["reason"],
                "score": link["score"],
                "score_items": loads(link["score_items_json"], []),
                "first_date": link["first_date"],
                "hub_case_ids": loads(link["hub_case_ids"], []),
                "copay_card_ids": loads(link["copay_card_ids"], []),
                "record_id": link["record_id"],
            }
        )
    files = _files_for_records(records)
    return {
        "daiichi_patient_id": daiichi,
        "records": records,
        "lineage": {"files": files, "records": records, "patient_id": daiichi},
        "similar": similar,
    }


def _files_for_records(records: list[dict]) -> list[dict]:
    if not records:
        return []
    ids = [record["record_id"] for record in records]
    placeholders = ",".join("?" for _ in ids)
    with DB() as db:
        rows = db.query(
            f"""
            SELECT DISTINCT f.id, f.name, f.source
            FROM pt_row rw
            JOIN pt_file f ON f.id = rw.file_id
            JOIN pt_record r ON r.source = rw.source AND r.vendor_patient_id = rw.vendor_patient_id
            WHERE r.id IN ({placeholders})
            """,
            ids,
        )
    return [{"id": row["id"], "name": row["name"], "source": row["source"]} for row in rows]


def _similar(db: DB, bundle: dict) -> list[dict]:
    links = bundle["links"]
    if not links:
        return []
    anchor = links[0]
    rows = db.query(
        """
        SELECT DISTINCT p.daiichi_patient_id, r.birth_year, r.sex, r.brand, r.prescriber_npi, r.prescriber_name
        FROM pt_link l
        JOIN pt_patient p ON p.id = l.patient_id
        JOIN pt_record r ON r.id = l.record_id
        WHERE p.retired_into IS NULL AND p.daiichi_patient_id != ?
        """,
        (bundle["patient"]["daiichi_patient_id"],),
    )
    found = []
    seen = set()
    for row in rows:
        if row["daiichi_patient_id"] in seen:
            continue
        if row["prescriber_npi"] != anchor["prescriber_npi"]:
            continue
        if row["sex"] != anchor["sex"] or row["brand"] != anchor["brand"]:
            continue
        if anchor["birth_year"] is None or row["birth_year"] is None:
            continue
        if abs(int(row["birth_year"]) - int(anchor["birth_year"])) > 1:
            continue
        seen.add(row["daiichi_patient_id"])
        found.append(
            {
                "daiichi_patient_id": row["daiichi_patient_id"],
                "birth_year": row["birth_year"],
                "prescriber": row["prescriber_name"],
            }
        )
        if len(found) >= 3:
            break
    return found


def patient_history(daiichi: str) -> dict:
    with DB() as db:
        bundle = _require(db, daiichi)
        reviews = db.query(
            """
            SELECT rv.id, rv.status, rv.resolved_at, rv.resolved_by, r.ref
            FROM pt_review rv JOIN pt_record r ON r.id = rv.record_id
            JOIN pt_link l ON l.record_id = r.id
            WHERE l.patient_id = ?
            """,
            (bundle["patient"]["id"],),
        )
    items = [
        {
            "at": bundle["patient"]["created_at"],
            "title": f"Daiichi patient ID created",
            "detail": bundle["links"][0]["ref"] if bundle["links"] else "",
        }
    ]
    for link in bundle["links"]:
        items.append(
            {
                "at": link["decided_at"] or link["first_date"],
                "title": f"{SOURCE_LABELS.get(link['source'], link['source'])} record {link['ref']} added",
                "detail": link["reason"] or link["layer"],
            }
        )
    for review in reviews:
        if review["status"] in {"assigned", "new_patient"}:
            items.append(
                {
                    "at": review["resolved_at"],
                    "title": f"{review['ref']} assigned by a reviewer" if review["status"] == "assigned" else f"{review['ref']} created as a new patient",
                    "detail": review["resolved_by"] or "data steward",
                    "review_id": review["id"],
                    "can_undo": True,
                }
            )
    return {"daiichi_patient_id": daiichi, "items": items}


def record_detail(ref: str) -> dict:
    with DB() as db:
        record = db.one("SELECT * FROM pt_record WHERE ref=?", (ref,))
        if record is None:
            raise NotFoundError("Record not found.")
        rows = db.query(
            """
            SELECT raw_json, held_back, hold_reason, event_date
            FROM pt_row
            WHERE source=? AND vendor_patient_id=? AND held_back=0
            ORDER BY event_date, id
            """,
            (record["source"], record["vendor_patient_id"]),
        )
        link = db.one(
            """
            SELECT p.daiichi_patient_id, l.layer, l.reason, l.score, l.score_items_json
            FROM pt_link l JOIN pt_patient p ON p.id = l.patient_id
            WHERE l.record_id=?
            """,
            (record["id"],),
        )
    return {
        "ref": record["ref"],
        "source": record["source"],
        "source_label": SOURCE_LABELS.get(record["source"], record["source"]),
        "vendor_patient_id": record["vendor_patient_id"],
        "hub_case_ids": loads(record["hub_case_ids"], []),
        "copay_card_ids": loads(record["copay_card_ids"], []),
        "birth_year": record["birth_year"],
        "sex": record["sex"],
        "zip3": record["zip3"],
        "prescriber": record["prescriber_name"],
        "doctor_id": record["doctor_id"],
        "brand": record["brand"],
        "payer_type": record["payer_type"],
        "daiichi_patient_id": link["daiichi_patient_id"] if link else None,
        "layer": link["layer"] if link else None,
        "reason": link["reason"] if link else "Waiting for a person",
        "score": link["score"] if link else None,
        "score_items": loads(link["score_items_json"], []) if link else [],
        "rows": [loads(row["raw_json"], {}) for row in rows],
    }


def _require(db: DB, daiichi: str) -> dict:
    bundle = _patient_bundle(db, daiichi)
    if bundle is None:
        raise NotFoundError("Patient not found.")
    return bundle


def _ref_for(bundle: dict, record_id: int) -> str | None:
    for link in bundle["links"]:
        if link["record_id"] == record_id:
            return link["ref"]
    return None


def review_queue(source: str | None = None) -> dict:
    with DB() as db:
        rows = db.query(
            """
            SELECT rv.*, r.ref, r.source, r.vendor_patient_id, r.birth_year, r.sex, r.zip3,
                   r.prescriber_name, r.brand, r.payer_type, r.first_date
            FROM pt_review rv JOIN pt_record r ON r.id = rv.record_id
            WHERE rv.status IN ('open', 'deferred')
            ORDER BY r.ref
            """
        )
        total_records = db.one("SELECT COUNT(*) AS n FROM pt_record")["n"]
        auto = db.one("SELECT COUNT(*) AS n FROM pt_link WHERE layer IN ('program_id','vendor_id','score')")["n"]
        assigned = db.one("SELECT COUNT(*) AS n FROM pt_review WHERE status IN ('assigned','new_patient')")["n"]
    items = []
    for row in rows:
        if source and row["source"] != source:
            continue
        top = loads(row["top3_json"], [])
        items.append(
            {
                "id": row["id"],
                "ref": row["ref"],
                "source": row["source"],
                "source_label": SOURCE_LABELS.get(row["source"], row["source"]),
                "vendor_patient_id": row["vendor_patient_id"],
                "best_score": top[0]["score"] if top else None,
                "candidates": len(top),
            }
        )
    counts = {"all": 0, "hub": 0, "pharmacy": 0, "claims": 0}
    for row in rows:
        counts["all"] += 1
        counts[row["source"]] = counts.get(row["source"], 0) + 1
    report = quality()
    return {
        "items": items,
        "counts": counts,
        "waiting": counts["all"],
        "mapped_automatically_pct": round(100 * auto / total_records) if total_records else 0,
        "assigned": int(assigned),
        "top_suggestion_correct": None if not report else report.get("top_suggestion_correct"),
        "open_reviews": None if not report else report.get("open_reviews"),
        "thresholds": {"auto": AUTO_MIN, "review": REVIEW_MIN, "margin": MARGIN},
    }


def review_detail(review_id: int) -> dict:
    with DB() as db:
        row = db.one(
            """
            SELECT rv.*, r.ref, r.source, r.vendor_patient_id, r.birth_year, r.sex, r.zip3,
                   r.prescriber_name, r.prescriber_npi, r.brand, r.payer_type, r.first_date,
                   r.hub_case_ids, r.copay_card_ids, r.doctor_id, r.row_count
            FROM pt_review rv JOIN pt_record r ON r.id = rv.record_id
            WHERE rv.id=?
            """,
            (review_id,),
        )
        if row is None:
            raise NotFoundError("Review case not found.")
        top = loads(row["top3_json"], [])
        candidates = []
        for index, item in enumerate(top):
            profile = _candidate_profile(db, item.get("daiichi_patient_id"))
            margin = None
            if index == 0 and len(top) > 1:
                margin = item["score"] - top[1]["score"]
            elif index == 0:
                margin = item["score"] - (-20)
            candidates.append(
                {
                    **item,
                    "suggested": index == 0 and (len(top) == 1 or (margin or 0) >= MARGIN),
                    "margin": margin if index == 0 else None,
                    "profile": profile,
                    "evidence": _evidence(row, profile, item.get("items") or []),
                }
            )
    return {
        "id": row["id"],
        "status": row["status"],
        "record": {
            "ref": row["ref"],
            "source": row["source"],
            "source_label": SOURCE_LABELS.get(row["source"], row["source"]),
            "vendor_patient_id": row["vendor_patient_id"],
            "birth_year": row["birth_year"],
            "sex": row["sex"],
            "zip3": row["zip3"],
            "prescriber": row["prescriber_name"],
            "doctor_id": row["doctor_id"],
            "brand": row["brand"],
            "payer_type": row["payer_type"],
            "first_date": row["first_date"],
            "first_date_label": fmt_date(row["first_date"]),
            "hub_case_ids": loads(row["hub_case_ids"], []),
            "copay_card_ids": loads(row["copay_card_ids"], []),
            "row_count": row["row_count"],
        },
        "candidates": candidates,
        "reasoning": loads(row["ai_reasoning_json"], {}),
        "fields": ["Program IDs", "Birth year", "Sex", "ZIP3", "Prescriber", "Product", "Payer type", "Dates line up"],
    }


def _candidate_profile(db: DB, daiichi: str | None) -> dict | None:
    if not daiichi:
        return None
    rows = db.query(
        """
        SELECT r.*, p.daiichi_patient_id
        FROM pt_link l
        JOIN pt_record r ON r.id = l.record_id
        JOIN pt_patient p ON p.id = l.patient_id
        WHERE p.daiichi_patient_id=?
        """,
        (daiichi,),
    )
    if not rows:
        return None
    anchor = rows[0]
    return {
        "daiichi_patient_id": daiichi,
        "birth_year": anchor["birth_year"],
        "sex": anchor["sex"],
        "zip3": anchor["zip3"],
        "prescriber": anchor["prescriber_name"],
        "prescriber_npi": anchor["prescriber_npi"],
        "brand": anchor["brand"],
        "payer_type": anchor["payer_type"],
        "sources": sorted({row["source"] for row in rows}),
        "record_count": len(rows),
        "hub_case_ids": sorted({case for row in rows for case in loads(row["hub_case_ids"], [])}),
        "copay_card_ids": sorted({case for row in rows for case in loads(row["copay_card_ids"], [])}),
    }


def _mark(same: bool, partial: bool = False, missing: bool = False, text: str = "") -> dict:
    if missing:
        return {"symbol": "—", "tone": "m", "text": text or "Not available"}
    if same:
        return {"symbol": "✓", "tone": "y", "text": text}
    if partial:
        return {"symbol": "≈", "tone": "p", "text": text}
    return {"symbol": "✗", "tone": "n", "text": text}


def _evidence(record, profile: dict | None, items: list[dict]) -> list[dict]:
    if profile is None:
        return []
    record_cases = set(loads(record["hub_case_ids"], []))
    record_cards = set(loads(record["copay_card_ids"], []))
    shared = bool(record_cases & set(profile["hub_case_ids"]) or record_cards & set(profile["copay_card_ids"]))
    birth_gap = None
    if record["birth_year"] is not None and profile["birth_year"] is not None:
        birth_gap = abs(int(record["birth_year"]) - int(profile["birth_year"]))
    if birth_gap is None:
        birth_cell = _mark(False, missing=True, text="Not available")
    elif birth_gap == 0:
        birth_cell = _mark(True, text=str(profile["birth_year"]))
    elif birth_gap == 1:
        birth_cell = _mark(False, partial=True, text=str(profile["birth_year"]))
    else:
        birth_cell = _mark(False, text=str(profile["birth_year"]))
    date_item = next((item for item in items if "date" in item.get("label", "").lower() or "fill" in item.get("label", "").lower() or "Therapy" in item.get("label", "") or "Claim" in item.get("label", "") or "pharmac" in item.get("label", "").lower()), None)
    date_points = date_item["points"] if date_item else None
    if date_item is None:
        date_cell = _mark(False, missing=True, text="Not available")
    elif date_points is None or date_points == 0:
        date_cell = _mark(False, missing=True, text=date_item["label"])
    elif date_points >= 3:
        date_cell = _mark(True, text=date_item["label"])
    elif date_points > 0:
        date_cell = _mark(False, partial=True, text=date_item["label"])
    else:
        date_cell = _mark(False, text=date_item["label"])
    return [
        {"field": "Program IDs", "record": "Present" if record_cases or record_cards else "None on record", "candidate": _mark(shared, missing=not shared, text="Shared" if shared else "None shared")},
        {"field": "Birth year", "record": record["birth_year"], "candidate": birth_cell},
        {"field": "Sex", "record": record["sex"], "candidate": _mark(record["sex"] == profile["sex"], text=profile["sex"] or "")},
        {"field": "ZIP3", "record": record["zip3"], "candidate": _mark(record["zip3"] == profile["zip3"], text=profile["zip3"] or "")},
        {"field": "Prescriber", "record": record["prescriber_name"], "candidate": _mark(record["prescriber_npi"] == profile["prescriber_npi"], text=profile["prescriber"] or "")},
        {"field": "Product", "record": record["brand"], "candidate": _mark(record["brand"] == profile["brand"], text=profile["brand"] or "")},
        {"field": "Payer type", "record": record["payer_type"], "candidate": _mark(record["payer_type"] == profile["payer_type"], partial=record["payer_type"] != profile["payer_type"], text=profile["payer_type"] or "")},
        {"field": "Dates line up", "record": fmt_date(record["first_date"]), "candidate": date_cell},
    ]


def _decide(review_id: int, status: str, target: str | None, actor: str) -> dict:
    with DB() as db:
        review = db.one("SELECT * FROM pt_review WHERE id=?", (review_id,))
        if review is None:
            raise NotFoundError("Review case not found.")
        if review["status"] not in {"open", "deferred"} and status != "open":
            raise ValidationAppError("This case is already decided. Undo it first.")
        if status == "assigned":
            patient = db.one(
                "SELECT id FROM pt_patient WHERE daiichi_patient_id=? AND retired_into IS NULL",
                (target,),
            )
            if patient is None:
                raise NotFoundError("Daiichi patient not found.")
        db.execute(
            """
            UPDATE pt_review
            SET status=?, target_patient_id=?, resolved_by=?, resolved_at=?
            WHERE id=?
            """,
            (status, target, actor if status != "open" else None, utc_now() if status != "open" else None, review_id),
        )
        db.execute(
            "INSERT INTO pt_audit (at, actor, action, details) VALUES (?, ?, ?, ?)",
            (utc_now(), actor, f"review_{status}", dumps({"review_id": review_id, "target": target})),
        )
        db.commit()
    if status == "deferred":
        return {"status": "deferred", "review_id": review_id}
    result = run_pipeline(f"Review {status}")
    return {"status": status, "daiichi_patient_id": target, "run_id": result.get("run_id"), "patients": result.get("patients"), "reviews": result.get("reviews")}


def assign_review(review_id: int, daiichi_patient_id: str, actor: str = "data steward") -> dict:
    if not daiichi_patient_id:
        raise ValidationAppError("daiichi_patient_id is required.")
    return _decide(review_id, "assigned", daiichi_patient_id, actor)


def new_patient_review(review_id: int, actor: str = "data steward") -> dict:
    return _decide(review_id, "new_patient", None, actor)


def defer_review(review_id: int, actor: str = "data steward") -> dict:
    return _decide(review_id, "deferred", None, actor)


def undo_review(review_id: int, actor: str = "data steward") -> dict:
    with DB() as db:
        review = db.one("SELECT * FROM pt_review WHERE id=?", (review_id,))
        if review is None:
            raise NotFoundError("Review case not found.")
        if review["status"] == "open":
            raise ValidationAppError("This case is already open.")
        db.execute(
            "UPDATE pt_review SET status='open', target_patient_id=NULL, resolved_by=NULL, resolved_at=NULL WHERE id=?",
            (review_id,),
        )
        db.execute(
            "INSERT INTO pt_audit (at, actor, action, details) VALUES (?, ?, ?, ?)",
            (utc_now(), actor, "review_undo", dumps({"review_id": review_id})),
        )
        db.commit()
    result = run_pipeline("Review undo")
    return {"status": "open", "run_id": result.get("run_id"), "reviews": result.get("reviews")}


def privacy() -> dict:
    with DB() as db:
        audit = db.query("SELECT * FROM pt_audit ORDER BY id DESC LIMIT 30")
        held = db.one("SELECT COALESCE(SUM(rows_held_back), 0) AS n FROM pt_file")["n"]
    report = quality()
    return {
        "received": {
            "identities": "None. No names, birth dates, addresses or phone numbers.",
            "vendor_patient_ids": "Hub, pharmacy and claims IDs, each valid only inside its own source.",
            "program_ids": "Hub case ID and copay card ID, used to link across sources.",
            "fields": "Birth year, sex, ZIP3, prescriber NPI, product, payer type, dates and quantities.",
            "daiichi_patient_id": "Issued by this system. It stays the same when the same records are processed again.",
        },
        "layers": [
            {"layer": "1", "evidence": "Hub case ID, copay card ID", "rule": "Exact match links, unless sex differs or birth years are more than 1 apart."},
            {"layer": "2", "evidence": "Vendor patient ID", "rule": "Rows with the same vendor patient ID in one source are one record."},
            {"layer": "3", "evidence": "Birth year, sex, ZIP3, prescriber, product, payer, dates", "rule": f"Score ≥ +{AUTO_MIN} and a lead of {MARGIN} points links automatically."},
            {"layer": "4", "evidence": "The 3 nearest patients", "rule": f"Score +{REVIEW_MIN} to +{AUTO_MIN}, or a lead under {MARGIN}: a person assigns."},
        ],
        "roles": [
            {"role": "Privacy officer", "vendor_ids": "Yes", "assign": "Yes", "journeys": "Yes", "dashboards": "Yes"},
            {"role": "Data steward", "vendor_ids": "Yes", "assign": "Yes", "journeys": "Yes, Daiichi IDs", "dashboards": "Yes"},
            {"role": "Analyst", "vendor_ids": "No", "assign": "No", "journeys": "Yes, Daiichi IDs", "dashboards": "Yes"},
            {"role": "Brand and field teams", "vendor_ids": "No", "assign": "No", "journeys": "No", "dashboards": "Yes, small groups hidden"},
        ],
        "checks": [
            {"title": "Identifier columns are rejected", "detail": "A file with a name, birth date, address, phone, email, SSN or MRN column is not loaded."},
            {"title": f"{int(held)} rows held back", "detail": "Rows with a bad date or a missing required value stay out of matching."},
            {"title": "Small-cell rule", "detail": f"Counts under {small_cell_min() or 11} are shown as <11." if small_cell_min() else "Small-cell rule off for synthetic demo data."},
            {"title": "What the model sees", "detail": "Birth year, sex, ZIP3, prescriber name, brand, payer, dates, quantities, pharmacy names, record refs and score items. Never a vendor patient ID, hub case ID or copay card ID."},
        ],
        "audit": [
            {"at": row["at"], "actor": row["actor"], "action": row["action"], "details": loads(row["details"], {})}
            for row in audit
        ],
        "quality": report,
        "small_cell_min": small_cell_min(),
    }


def evaluation() -> dict:
    report = quality()
    if report is None:
        return {"available": False}
    report["available"] = True
    return report
