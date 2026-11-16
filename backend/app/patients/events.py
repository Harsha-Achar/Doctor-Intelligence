"""Clinical events, status and next dose for one Daiichi patient."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.patients.config import product_by_brand
from app.patients.textutil import parse_iso


def _sort_key(row: dict) -> str:
    return row.get("event_date") or ""


def build_events(records: list[dict], rows_by_record: dict[int, list[dict]]) -> list[dict]:
    events: list[dict] = []
    hub_records = [r for r in records if r["source"] == "hub"]
    pharmacy_records = [r for r in records if r["source"] == "pharmacy"]
    claim_records = [r for r in records if r["source"] == "claims"]

    for record in sorted(hub_records, key=lambda r: r.get("first_date") or ""):
        for row in sorted(rows_by_record.get(record["id"], []), key=_sort_key):
            title, kind, detail = _hub_event(row.get("status") or "")
            events.append(_event(record, row.get("event_date"), kind, title, detail, None, None, {}, row))

    if len(hub_records) > 1:
        later = sorted(hub_records, key=lambda r: r.get("first_date") or "")[1]
        events.append(
            _event(
                later,
                later.get("first_date"),
                "note",
                "Possible duplicate hub enrollment",
                "A second hub record matches this patient.",
                None,
                None,
                {"duplicate_hub": True},
            )
        )

    claim_rows = []
    for record in claim_records:
        for row in rows_by_record.get(record["id"], []):
            claim_rows.append((record, row))
    claim_rows.sort(key=lambda pair: pair[1].get("event_date") or "")

    dose_rows = []
    for record in pharmacy_records:
        for row in rows_by_record.get(record["id"], []):
            status = (row.get("status") or "").strip()
            if status.lower().startswith("discontinued"):
                reason = status.split("-", 1)[1].strip() if "-" in status else status
                events.append(
                    _event(record, row.get("event_date"), "stop", "Discontinued", reason, row.get("quantity"), row.get("pharmacy_name"), {"reason": reason}, row)
                )
                continue
            dose_rows.append((record, row))
    dose_rows.sort(key=lambda pair: (pair[1].get("event_date") or "", pair[0]["ref"]))

    if dose_rows:
        _append_doses(events, dose_rows, claim_rows)
    elif claim_rows:
        _append_claim_doses(events, claim_rows)

    events.sort(key=lambda event: (event["date"] or "", 0 if event["kind"] == "note" else 1, event["title"]))
    return events


def _append_doses(events: list[dict], dose_rows: list[tuple], claim_rows: list[tuple]) -> None:
    used: set[int] = set()
    previous = None
    for index, (record, row) in enumerate(dose_rows, start=1):
        product = product_by_brand(record.get("brand") or "") or {}
        qty = row.get("quantity")
        flags: dict[str, Any] = {
            "dose_index": index,
            "days_supply": row.get("days_supply"),
            "unit": product.get("unit"),
            "on_schedule": True,
            "brand": record.get("brand"),
        }
        day = parse_iso(row.get("event_date"))
        if previous and day:
            gap = (day - previous["day"]).days
            supply = int(previous["supply"] or 0)
            if supply and gap > supply + 7:
                late = gap - supply
                flags["late"] = True
                flags["days_late"] = late
                flags["on_schedule"] = False
                events.append(
                    _event(
                        record,
                        row.get("event_date"),
                        "note",
                        "Dose delayed",
                        f"{late} days late",
                        qty,
                        row.get("pharmacy_name"),
                        {"days_late": late},
                        row,
                    )
                )
            if previous["qty"] is not None and qty is not None and float(qty) < float(previous["qty"]):
                flags["reduced"] = True
                flags["reduced_from"] = previous["qty"]
                flags["on_schedule"] = False
                unit = product.get("unit") or "units"
                events.append(
                    _event(
                        record,
                        row.get("event_date"),
                        "note",
                        "Dose reduced",
                        f"{_num(previous['qty'])} → {_num(qty)} {unit}",
                        qty,
                        row.get("pharmacy_name"),
                        {"reduced_from": previous["qty"], "reduced_to": qty},
                        row,
                    )
                )
        pharmacy = row.get("pharmacy_name") or ""
        vendor_changed = previous and previous["vendor"] != record["vendor_patient_id"]
        name_changed = previous and previous["pharmacy"] and pharmacy and previous["pharmacy"] != pharmacy
        if previous and (vendor_changed or name_changed):
            flags["new_pharmacy"] = True
            flags["on_schedule"] = False
            old_name = previous["pharmacy"] or previous["vendor"]
            new_name = pharmacy or record["vendor_patient_id"]
            events.append(
                _event(
                    record,
                    row.get("event_date"),
                    "note",
                    "Switched specialty pharmacy",
                    f"{old_name} → {new_name}",
                    qty,
                    pharmacy,
                    {"switch": True, "old": old_name, "new": new_name},
                    row,
                )
            )
        claim = _closest_claim(claim_rows, used, record.get("brand"), day)
        if claim is not None:
            used.add(id(claim[1]))
            flags["claim_paid"] = True
            flags["claim_ref"] = claim[0]["ref"]
            flags["claim_record_id"] = claim[0]["id"]
        title = "Fill dispensed" if (record.get("brand") == "Brand C") else "Dose given"
        unit = product.get("unit") or ""
        detail = f"{_num(qty)} × {unit}".strip()
        if pharmacy:
            detail = f"{detail} · {pharmacy}"
        events.append(_event(record, row.get("event_date"), "dose", title, detail, qty, pharmacy, flags, row))
        previous = {
            "day": day,
            "supply": row.get("days_supply"),
            "qty": qty,
            "pharmacy": pharmacy,
            "vendor": record["vendor_patient_id"],
        }


def _append_claim_doses(events: list[dict], claim_rows: list[tuple]) -> None:
    for index, (record, row) in enumerate(claim_rows, start=1):
        product = product_by_brand(record.get("brand") or "") or {}
        flags = {
            "dose_index": index,
            "days_supply": product.get("cycle_days"),
            "unit": product.get("unit"),
            "on_schedule": True,
            "from_claims": True,
            "claim_paid": True,
            "claim_ref": record["ref"],
            "brand": record.get("brand"),
        }
        qty = row.get("quantity")
        title = "Fill dispensed" if record.get("brand") == "Brand C" else "Dose given"
        detail = f"{_num(qty)} × {product.get('unit') or ''}".strip()
        events.append(_event(record, row.get("event_date"), "dose", title, detail, qty, None, flags, row))


def _closest_claim(claim_rows, used, brand, day):
    if day is None:
        return None
    best = None
    best_gap = None
    for record, row in claim_rows:
        if id(row) in used or record.get("brand") != brand:
            continue
        other = parse_iso(row.get("event_date"))
        if other is None:
            continue
        gap = abs((other - day).days)
        if gap <= 4 and (best_gap is None or gap < best_gap):
            best = (record, row)
            best_gap = gap
    return best


def _hub_event(status: str) -> tuple[str, str, str]:
    text = status.strip()
    lowered = text.lower()
    if lowered == "enrolled":
        return "Enrolled in patient support program", "access", "Hub enrollment"
    if lowered == "prior authorization approved":
        return "Prior authorization approved", "access", ""
    if lowered == "prior authorization denied":
        return "Prior authorization denied", "access", ""
    if lowered == "approved on appeal":
        return "Approved on appeal", "access", ""
    if lowered.startswith("case closed"):
        reason = text.split("-", 1)[1].strip() if "-" in text else ""
        return "Case closed", "stop", reason
    return text or "Hub update", "access", ""


def _event(record, when, kind, title, detail, quantity, pharmacy, flags, source_row=None) -> dict:
    stored = dict(flags or {})
    if source_row is not None and source_row.get("file_kind") == "uploaded":
        stored["uploaded"] = True
    return {
        "date": when,
        "source": record["source"],
        "record_id": record["id"],
        "kind": kind,
        "title": title,
        "detail": detail,
        "quantity": quantity,
        "pharmacy": pharmacy,
        "flags": stored,
    }


def _num(value) -> str:
    if value is None:
        return ""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def derive_status(events: list[dict], sources: set[str]) -> dict:
    doses = [event for event in events if event["kind"] == "dose"]
    stops = [event for event in events if event["kind"] == "stop"]
    if sources == {"claims"} or (sources <= {"claims"} and "claims" in sources and "pharmacy" not in sources and "hub" not in sources):
        status = "Claims only"
    else:
        case_closed = [event for event in stops if event["source"] == "hub"]
        discontinued = [event for event in stops if event["source"] == "pharmacy"]
        if case_closed and not doses:
            status = "Never started"
        elif discontinued:
            stop_on = max(event["date"] for event in discontinued)
            later = [event for event in doses if (event["date"] or "") > stop_on]
            status = "On therapy" if later else "Stopped"
        elif doses:
            status = "On therapy"
        elif "hub" in sources:
            status = "Waiting to start"
        elif "claims" in sources:
            status = "Claims only"
        else:
            status = "Waiting to start"
    last = doses[-1] if doses else None
    next_dose = None
    if last and status in {"On therapy", "Claims only"}:
        day = parse_iso(last["date"])
        supply = (last.get("flags") or {}).get("days_supply")
        if day and supply:
            next_dose = (day + timedelta(days=int(supply))).isoformat()
    stop = next((event for event in reversed(events) if event["kind"] == "stop"), None)
    pharmacies = [event.get("pharmacy") for event in doses if event.get("pharmacy")]
    switched = any((event.get("flags") or {}).get("switch") or (event.get("flags") or {}).get("new_pharmacy") for event in events)
    return {
        "status": status,
        "next_dose": next_dose,
        "last_dose": last["date"] if last else None,
        "first_dose": doses[0]["date"] if doses else None,
        "dose_count": len(doses),
        "current_quantity": last.get("quantity") if last else None,
        "current_unit": (last.get("flags") or {}).get("unit") if last else None,
        "pharmacy": pharmacies[-1] if pharmacies else None,
        "previous_pharmacy": pharmacies[0] if len(set(pharmacies)) > 1 else None,
        "switched": switched or len(set(pharmacies)) > 1,
        "stop_date": stop["date"] if stop and status in {"Stopped", "Never started"} else None,
        "stop_reason": (stop.get("detail") or stop.get("title")) if stop else None,
    }
