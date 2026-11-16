"""Pairwise score used by layer 3. Hard stops never become a candidate."""

from __future__ import annotations

from datetime import date

from app.patients.config import WEIGHTS


def _days(a: date, b: date) -> int:
    return abs((a - b).days)


def closest_days(left: list[date], right: list[date]) -> int | None:
    if not left or not right:
        return None
    return min(_days(a, b) for a in left for b in right)


def score_pair(
    left: dict,
    right: dict,
    *,
    incoming_is_hub: bool,
    candidate_has_hub: bool,
) -> dict | None:
    """Score one record pair. `left` is the incoming record."""
    if left.get("sex") != right.get("sex"):
        return None
    by_l = left.get("birth_year")
    by_r = right.get("birth_year")
    if by_l is None or by_r is None or abs(int(by_l) - int(by_r)) > 1:
        return None

    items: list[tuple[str, int]] = [("Starting point", WEIGHTS["start"])]
    items.append(("Same sex", WEIGHTS["sex_same"]))
    if int(by_l) == int(by_r):
        items.append(("Same birth year", WEIGHTS["birth_same"]))
    else:
        items.append(("Birth year off by 1", WEIGHTS["birth_off_by_one"]))

    zip_l, zip_r = left.get("zip3") or "", right.get("zip3") or ""
    if zip_l and zip_r and zip_l == zip_r:
        items.append(("Same ZIP3", WEIGHTS["zip_same"]))
    elif zip_l and zip_r:
        items.append(("Different ZIP3", WEIGHTS["zip_different"]))

    npi_l, npi_r = left.get("prescriber_npi") or "", right.get("prescriber_npi") or ""
    if npi_l and npi_r and npi_l == npi_r:
        name = left.get("prescriber_name") or right.get("prescriber_name") or "same NPI"
        items.append((f"Same prescriber ({name})", WEIGHTS["prescriber_same"]))
    elif npi_l and npi_r:
        items.append(("Different prescriber", WEIGHTS["prescriber_different"]))

    brand_l, brand_r = left.get("brand") or "", right.get("brand") or ""
    if brand_l and brand_r and brand_l == brand_r:
        items.append(("Same product", WEIGHTS["product_same"]))
    elif brand_l and brand_r:
        items.append(("Different product", WEIGHTS["product_different"]))

    pay_l, pay_r = left.get("payer_type") or "", right.get("payer_type") or ""
    if pay_l and pay_r and pay_l == pay_r:
        items.append(("Same payer type", WEIGHTS["payer_same"]))
    elif pay_l and pay_r:
        items.append(("Different payer type", WEIGHTS["payer_different"]))

    items.extend(_date_items(left, right))
    if incoming_is_hub and candidate_has_hub:
        items.append(("Candidate already has a hub enrollment", WEIGHTS["hub_already"]))

    total = sum(points for _, points in items)
    return {"score": total, "items": [{"label": label, "points": points} for label, points in items]}


def _date_items(left: dict, right: dict) -> list[tuple[str, int]]:
    pair = tuple(sorted((left["source"], right["source"])))
    if pair == ("claims", "pharmacy"):
        gap = closest_days(left["dates"], right["dates"])
        if gap is None:
            return [("Dates not available", 0)]
        if gap <= 4:
            return [("Claim within 4 days of a dispense", WEIGHTS["rx_claim_within_4"])]
        if gap <= 30:
            return [("Claim within 30 days of a dispense", WEIGHTS["rx_claim_within_30"])]
        return [("Claim and dispense dates are far apart", WEIGHTS["rx_claim_otherwise"])]
    if pair in {("claims", "hub"), ("hub", "pharmacy")}:
        hub = left if left["source"] == "hub" else right
        other = right if left["source"] == "hub" else left
        if not hub["dates"] or not other["dates"]:
            return [("Dates not available", 0)]
        enrolled = min(hub["dates"])
        started = min(other["dates"])
        delta = (started - enrolled).days
        if 0 <= delta <= 90:
            return [("Therapy starts within 90 days of enrollment", WEIGHTS["hub_therapy_within_90"])]
        return [("Therapy dates do not follow this enrollment", WEIGHTS["hub_therapy_otherwise"])]
    if pair == ("pharmacy", "pharmacy"):
        if not left["dates"] or not right["dates"]:
            return [("Dates not available", 0)]
        gap = _days(min(left["dates"]), min(right["dates"]))
        if gap > 40:
            return [("New fills start more than 40 days after the earlier pharmacy record", WEIGHTS["pharmacy_transfer"])]
        return [("Overlapping fills at two pharmacies", WEIGHTS["pharmacy_overlap"])]
    if pair == ("claims", "claims"):
        return [("A second claims patient ID", WEIGHTS["claims_second_id"])]
    return [("Same source", 0)]
