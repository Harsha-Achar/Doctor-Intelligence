"""Read vendor CSVs. Reject identifier columns. Hold back bad rows. Skip known checksums."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.patients.config import FORBIDDEN_HEADERS, product_by_code

REQUIRED = {
    "hub": ["vendor_patient_id", "event", "event_date", "birth_year", "sex", "zip3", "prescriber_npi", "product"],
    "pharmacy": [
        "vendor_patient_id",
        "event_date",
        "product",
        "quantity",
        "days_supply",
        "event",
        "birth_year",
        "sex",
        "zip3",
        "prescriber_npi",
    ],
    "claims": [
        "vendor_patient_id",
        "event_date",
        "product",
        "birth_year",
        "sex",
        "zip3",
        "prescriber_npi",
    ],
}

# Source-specific column wins when several aliases are present.
ALIASES: dict[str, list[str]] = {
    "vendor_patient_id": [
        "hub_patient_id",
        "sp_patient_id",
        "claims_patient_id",
        "pharmacy_patient_id",
        "vendor_patient_id",
        "patient_id",
    ],
    "hub_case_id": ["hub_case_id", "case_id"],
    "copay_card_id": ["copay_card_id", "copay_id"],
    "event_date": ["event_date", "fill_date", "service_date", "enrollment_date", "date"],
    "birth_year": ["birth_year", "year_of_birth", "yob"],
    "sex": ["sex", "gender"],
    "zip3": ["zip3", "zip"],
    "prescriber_npi": ["prescriber_npi", "rendering_npi", "npi"],
    "product": ["product", "ndc", "product_code", "brand"],
    "payer_type": ["payer_type", "payer"],
    "pharmacy_name": ["pharmacy_name", "pharmacy"],
    "quantity": ["quantity", "units", "qty"],
    "days_supply": ["days_supply"],
    "event": ["event", "status", "claim_type"],
    "claim_id": ["claim_id"],
    "claim_type": ["claim_type"],
}

FIELD_LABELS = {
    "vendor_patient_id": "Vendor patient ID",
    "hub_case_id": "Hub case ID",
    "copay_card_id": "Copay card ID",
    "event_date": "Event, fill or service date",
    "birth_year": "Birth year",
    "sex": "Sex",
    "zip3": "ZIP3",
    "prescriber_npi": "Prescriber NPI",
    "product": "Product or NDC",
    "payer_type": "Payer type",
    "pharmacy_name": "Pharmacy name",
    "quantity": "Quantity",
    "days_supply": "Days supply",
    "event": "Event or status",
    "claim_id": "Claim ID",
    "claim_type": "Claim type",
}


@dataclass
class ParsedFile:
    source: str
    name: str
    checksum: str
    headers: list[str]
    mapping: list[dict[str, str]]
    identifier_ok: bool
    identifier_message: str
    missing_required: list[str]
    rejected: bool
    reject_reason: str
    rows_ok: list[dict[str, Any]] = field(default_factory=list)
    rows_held: list[dict[str, Any]] = field(default_factory=list)
    period: str = ""


def checksum_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _norm_header(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_")


def forbidden_headers(headers: list[str]) -> list[str]:
    found = []
    for header in headers:
        if _norm_header(header) in FORBIDDEN_HEADERS:
            found.append(header)
    return found


def column_map(headers: list[str], source: str) -> dict[str, str]:
    normalized = {_norm_header(h): h for h in headers}
    preferred = {
        "hub": {"vendor_patient_id": "hub_patient_id", "event_date": "event_date", "product": "product", "event": "event"},
        "pharmacy": {
            "vendor_patient_id": "sp_patient_id",
            "event_date": "fill_date",
            "product": "ndc",
            "event": "status",
            "quantity": "quantity",
        },
        "claims": {
            "vendor_patient_id": "claims_patient_id",
            "event_date": "service_date",
            "product": "product_code",
            "event": "claim_type",
            "quantity": "units",
            "claim_type": "claim_type",
        },
    }[source]
    chosen: dict[str, str] = {}
    for field_name, aliases in ALIASES.items():
        order = aliases
        pref = preferred.get(field_name)
        if pref:
            order = [pref] + [a for a in aliases if a != pref]
        for alias in order:
            if alias in normalized:
                chosen[field_name] = normalized[alias]
                break
    return chosen


def mapping_rows(headers: list[str], source: str) -> list[dict[str, str]]:
    chosen = column_map(headers, source)
    required = set(REQUIRED[source])
    rows = []
    for field_name, label in FIELD_LABELS.items():
        column = chosen.get(field_name, "")
        if column:
            state = "Mapped"
        elif field_name in required:
            state = "Missing"
        else:
            state = "Not in file"
        rows.append({"field": field_name, "label": label, "column": column, "state": state, "required": field_name in required})
    return rows


def _parse_date(value: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _sex(value: str) -> str | None:
    text = (value or "").strip().upper()
    if text in {"M", "MALE"}:
        return "M"
    if text in {"F", "FEMALE"}:
        return "F"
    return None


def _year(value: str) -> int | None:
    text = (value or "").strip()
    if not text.isdigit():
        return None
    year = int(text)
    if 1900 <= year <= 2100:
        return year
    return None


def _zip3(value: str) -> str | None:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) < 3:
        return None
    return digits[:3]


def _npi(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return digits if len(digits) == 10 else ""


def _num(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_csv(source: str, name: str, payload: bytes) -> ParsedFile:
    if source not in REQUIRED:
        return ParsedFile(
            source=source,
            name=name,
            checksum=checksum_bytes(payload),
            headers=[],
            mapping=[],
            identifier_ok=False,
            identifier_message="Unknown source.",
            missing_required=[],
            rejected=True,
            reject_reason="Choose hub, pharmacy or claims.",
        )
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    digest = checksum_bytes(payload)
    blocked = forbidden_headers(headers)
    mapping = mapping_rows(headers, source)
    missing = [row["label"] for row in mapping if row["state"] == "Missing"]
    if blocked:
        names = ", ".join(blocked)
        return ParsedFile(
            source=source,
            name=name,
            checksum=digest,
            headers=headers,
            mapping=mapping,
            identifier_ok=False,
            identifier_message=f"This file has identifier columns ({names}). It was not loaded.",
            missing_required=missing,
            rejected=True,
            reject_reason=f"Identifier columns are not allowed: {names}.",
        )
    if missing:
        return ParsedFile(
            source=source,
            name=name,
            checksum=digest,
            headers=headers,
            mapping=mapping,
            identifier_ok=True,
            identifier_message="No names, birth dates, addresses, phone numbers or other identifiers in the header.",
            missing_required=missing,
            rejected=True,
            reject_reason="Required columns are missing: " + ", ".join(missing) + ".",
        )
    chosen = column_map(headers, source)
    ok: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    dates: list[str] = []
    for raw in reader:
        if not any((v or "").strip() for v in raw.values()):
            continue
        item, reason = _parse_row(source, raw, chosen)
        if reason:
            held.append({"raw": raw, "reason": reason})
        else:
            ok.append({"raw": raw, "parsed": item})
            dates.append(item["event_date"])
    period = ""
    if dates:
        period = f"{min(dates)[:7]} → {max(dates)[:7]}"
    return ParsedFile(
        source=source,
        name=name,
        checksum=digest,
        headers=headers,
        mapping=mapping,
        identifier_ok=True,
        identifier_message="No names, birth dates, addresses, phone numbers or other identifiers in the header.",
        missing_required=[],
        rejected=False,
        reject_reason="",
        rows_ok=ok,
        rows_held=held,
        period=period,
    )


def _cell(raw: dict[str, Any], column: str) -> str:
    if not column:
        return ""
    return str(raw.get(column) or "").strip()


def _parse_row(source: str, raw: dict[str, Any], chosen: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
    def col(field_name: str) -> str:
        return _cell(raw, chosen.get(field_name, ""))

    vendor = col("vendor_patient_id")
    if not vendor:
        return None, "Missing vendor patient ID"
    event_date = _parse_date(col("event_date"))
    if not event_date:
        return None, "Bad or missing date"
    year = _year(col("birth_year"))
    if year is None:
        return None, "Bad or missing birth year"
    sex = _sex(col("sex"))
    if not sex:
        return None, "Bad or missing sex"
    zip3 = _zip3(col("zip3"))
    if not zip3:
        return None, "Bad or missing ZIP3"
    product_raw = col("product")
    product = product_by_code(product_raw)
    if product is None:
        return None, "Unknown product"
    quantity = _num(col("quantity"))
    days_supply = _num(col("days_supply"))
    if source == "pharmacy":
        if quantity is None:
            return None, "Bad or missing quantity"
        if days_supply is None:
            return None, "Bad or missing days supply"
    parsed = {
        "vendor_patient_id": vendor,
        "event_date": event_date,
        "birth_year": year,
        "sex": sex,
        "zip3": zip3,
        "prescriber_npi": _npi(col("prescriber_npi")),
        "brand": product["brand"],
        "payer_type": col("payer_type"),
        "hub_case_id": col("hub_case_id"),
        "copay_card_id": col("copay_card_id"),
        "pharmacy_name": col("pharmacy_name"),
        "quantity": quantity,
        "days_supply": int(days_supply) if days_supply is not None else None,
        "status": col("event"),
        "product_code": product_raw,
        "claim_id": col("claim_id"),
        "claim_type": col("claim_type") or (col("event") if source == "claims" else ""),
    }
    return parsed, ""
