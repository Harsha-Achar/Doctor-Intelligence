"""Read-only lookup of an existing doctor by NPI. Does not change doctor matching."""

from __future__ import annotations

import re


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def lookup_doctor_by_npi(npi: str) -> dict:
    """Return {doctor_id, name}. Unknown NPIs display as Unknown prescriber.

    Points in the matcher use the NPI itself. This lookup is only for the name and the link.
    """
    digits = _digits(npi)
    if len(digits) != 10:
        return {"doctor_id": None, "name": "Unknown prescriber"}
    try:
        from app.api.dependencies import get_repository

        doctors = get_repository().list_doctors()
    except Exception:
        return {"doctor_id": None, "name": "Unknown prescriber"}
    for doctor in doctors:
        if _digits(doctor.get("official_npi")) == digits:
            return {
                "doctor_id": doctor.get("doctor_id"),
                "name": doctor.get("preferred_name") or "Unknown prescriber",
            }
    return {"doctor_id": None, "name": "Unknown prescriber"}
