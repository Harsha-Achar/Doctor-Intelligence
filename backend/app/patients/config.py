"""Patient analytics settings. Reads env and backend/.env. Does not change app settings."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Fixed weights. There is not enough labeled data to estimate these.
WEIGHTS = {
    "start": -12,
    "sex_same": 1,
    "birth_same": 5,
    "birth_off_by_one": -3,
    "zip_same": 4,
    "zip_different": -2,
    "prescriber_same": 5,
    "prescriber_different": -2,
    "product_same": 3,
    "product_different": -6,
    "payer_same": 1,
    "payer_different": -1,
    "rx_claim_within_4": 6,
    "rx_claim_within_30": 2,
    "rx_claim_otherwise": -1,
    "hub_therapy_within_90": 3,
    "hub_therapy_otherwise": -1,
    "pharmacy_transfer": 2,
    "pharmacy_overlap": -2,
    "claims_second_id": -4,
    "hub_already": -3,
}

AUTO_MIN = 10
REVIEW_MIN = 3
MARGIN = 3
# Phantom runner-up when a record has only one candidate, so a clear score can still auto-link.
LONE_RUNNER_UP = -20

PRODUCTS = (
    {
        "brand": "Brand A",
        "description": "HER2 infusion",
        "codes": ("0000-0001", "J9415"),
        "unit": "100 mg vials",
        "normal_quantity": 3,
        "cycle_days": 21,
    },
    {
        "brand": "Brand B",
        "description": "TROP2 infusion",
        "codes": ("0000-0002", "J9416"),
        "unit": "180 mg vials",
        "normal_quantity": 4,
        "cycle_days": 21,
    },
    {
        "brand": "Brand C",
        "description": "Oral AML tablet",
        "codes": ("0000-0003",),
        "unit": "40 mg tablets",
        "normal_quantity": 60,
        "cycle_days": 30,
    },
)

# ZIP3 prefixes are a public geography reference, used only to label analytics.
ZIP3_STATE = {
    "303": "GA",
    "981": "WA",
    "606": "IL",
    "850": "AZ",
    "554": "MN",
    "441": "OH",
    "752": "TX",
    "972": "OR",
    "282": "NC",
    "021": "MA",
    "331": "FL",
}

FORBIDDEN_HEADERS = {
    "first_name",
    "last_name",
    "full_name",
    "patient_name",
    "name",
    "dob",
    "date_of_birth",
    "birth_date",
    "ssn",
    "address",
    "street",
    "phone",
    "email",
    "mrn",
}

SOURCE_LABELS = {
    "hub": "Hub",
    "pharmacy": "Specialty pharmacy",
    "claims": "Claims",
}

SOURCE_BLURB = {
    "hub": "Enrollments, benefits checks, prior authorizations",
    "pharmacy": "Dispenses, refills, status and transfers",
    "claims": "Pharmacy and medical claims from the data vendor",
}

HISTORICAL_FILES = (
    ("hub", "hub_enrollments.csv"),
    ("pharmacy", "specialty_pharmacy_dispenses.csv"),
    ("claims", "claims.csv"),
)


def _dotenv() -> dict[str, str]:
    path = BACKEND_ROOT / ".env"
    found: dict[str, str] = {}
    if not path.exists():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def _setting(name: str, default: str) -> str:
    if os.environ.get(name, "").strip():
        return os.environ[name].strip()
    return _dotenv().get(name, default).strip() or default


def patient_data_dir() -> Path:
    raw = _setting("PATIENT_DATA_DIR", "patient-data")
    path = Path(raw)
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return path.resolve()


def answer_key_path() -> Path:
    return patient_data_dir() / "answer_key" / "patient_answer_key.csv"


def small_cell_min() -> int:
    raw = _setting("SMALL_CELL_MIN", "11")
    try:
        return int(raw)
    except ValueError:
        return 11


def product_by_code(value: str) -> dict | None:
    text = (value or "").strip().upper().replace(" ", "")
    if not text:
        return None
    for product in PRODUCTS:
        for code in product["codes"]:
            if text == code.upper().replace(" ", "") or text.endswith(code.upper()):
                return product
    lowered = (value or "").strip().lower()
    for product in PRODUCTS:
        if lowered == product["brand"].lower():
            return product
    return None


def product_by_brand(brand: str) -> dict | None:
    for product in PRODUCTS:
        if product["brand"] == brand:
            return product
    return None
