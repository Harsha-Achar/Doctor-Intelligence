"""Journey analytics computed from linked patients."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.patients.config import ZIP3_STATE, product_by_brand, small_cell_min
from app.patients.db import DB, loads
from app.patients.textutil import parse_iso, suppress_count


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2)


def _kaplan(pairs: list[tuple[int, bool]]) -> list[list[float]]:
    ordered = sorted(pairs)
    at_risk = len(ordered)
    survival = 1.0
    points = [[0, 1.0]]
    index = 0
    while index < len(ordered):
        day = ordered[index][0]
        deaths = censored = 0
        while index < len(ordered) and ordered[index][0] == day:
            if ordered[index][1]:
                deaths += 1
            else:
                censored += 1
            index += 1
        if deaths and at_risk:
            survival *= 1 - deaths / at_risk
            points.append([day, round(survival, 4)])
        at_risk -= deaths + censored
    return points


def _at(points: list[list[float]], day: int) -> float:
    value = 1.0
    for when, share in points:
        if when <= day:
            value = share
        else:
            break
    return value


def journey_analytics(brand: str | None = None, payer: str | None = None) -> dict:
    minimum = small_cell_min()
    with DB() as db:
        as_of = (db.one("SELECT MAX(event_date) AS d FROM pt_row WHERE held_back=0") or {"d": None})["d"]
        patients = db.query(
            """
            SELECT p.id, p.daiichi_patient_id, s.facts_json
            FROM pt_patient p
            LEFT JOIN pt_summary s ON s.patient_id = p.id
            WHERE p.retired_into IS NULL
            """
        )
        link_rows = db.query(
            """
            SELECT l.patient_id, l.layer, r.source, r.prescriber_npi, r.prescriber_name, r.doctor_id, r.zip3, r.brand, r.payer_type
            FROM pt_link l JOIN pt_record r ON r.id = l.record_id
            """
        )
        events = db.query("SELECT patient_id, date, source, kind, title, detail FROM pt_event")
    by_patient_links: dict[int, list] = defaultdict(list)
    for row in link_rows:
        by_patient_links[row["patient_id"]].append(row)
    by_patient_events: dict[int, list] = defaultdict(list)
    for row in events:
        by_patient_events[row["patient_id"]].append(row)

    cohort = []
    for patient in patients:
        facts = loads(patient["facts_json"], {}) or {}
        links = by_patient_links.get(patient["id"], [])
        if brand and facts.get("therapy", {}).get("brand") != brand and not any(link["brand"] == brand for link in links):
            continue
        payer_value = facts.get("payer_type") or (links[0]["payer_type"] if links else "")
        if payer and payer_value != payer:
            continue
        sources = sorted({link["source"] for link in links})
        ev = by_patient_events.get(patient["id"], [])
        prescriber = next((link for link in links if link["doctor_id"]), links[0] if links else None)
        zip3 = next((link["zip3"] for link in links if link["zip3"]), "")
        cohort.append(
            {
                "id": patient["daiichi_patient_id"],
                "patient_pk": patient["id"],
                "facts": facts,
                "sources": sources,
                "events": ev,
                "payer": payer_value,
                "brand": (facts.get("therapy") or {}).get("brand"),
                "prescriber": (prescriber["prescriber_name"] if prescriber else None) or "Unknown prescriber",
                "doctor_id": prescriber["doctor_id"] if prescriber else None,
                "zip3": zip3,
                "state": ZIP3_STATE.get(zip3 or "", zip3 or "Unknown"),
                "layers": sorted({link["layer"] for link in links if link["layer"]}),
            }
        )

    def show(count: int) -> int | str:
        return suppress_count(count, minimum)

    as_of_day = parse_iso(as_of) or date.today()
    hub = [item for item in cohort if "hub" in item["sources"]]
    treated = [item for item in cohort if item["facts"].get("dose_count")]
    # A pharmacy "Shipped" row becomes a dose. A claims line does not: claim_type is
    # Medical or Pharmacy, and the file has no paid or administered flag.
    for item in cohort:
        item["dispensed"] = any(event["source"] == "pharmacy" and event["kind"] == "dose" for event in item["events"])
    dispensed = list(dict.fromkeys(item["id"] for item in cohort if item["dispensed"]))
    discontinued = list(
        dict.fromkeys(item["id"] for item in cohort if item["dispensed"] and item["facts"].get("status") == "Stopped")
    )
    never = [item for item in hub if item["facts"].get("status") == "Never started"]
    stopped = [item for item in cohort if item["facts"].get("status") == "Stopped"]
    delays = [item for item in treated if item["facts"].get("delays")]
    outside = [item for item in treated if "hub" not in item["sources"]]
    multi = [item for item in cohort if len(item["sources"]) > 1]

    def enrolled_on(item) -> date | None:
        for event in item["events"]:
            if event["kind"] == "access" and "enrolled" in (event["title"] or "").lower():
                return parse_iso(event["date"])
        hub_dates = [parse_iso(event["date"]) for event in item["events"] if event["source"] == "hub"]
        hub_dates = [value for value in hub_dates if value]
        return min(hub_dates) if hub_dates else None

    def pa_on(item) -> date | None:
        dates = []
        for event in item["events"]:
            title = (event["title"] or "").lower()
            if "prior authorization" in title or "appeal" in title:
                parsed = parse_iso(event["date"])
                if parsed:
                    dates.append(parsed)
        return min(dates) if dates else None

    def first_on(item) -> date | None:
        return parse_iso(item["facts"].get("first_dose"))

    ttt = []
    for item in treated:
        start = enrolled_on(item)
        first = first_on(item)
        if start and first and first >= start:
            ttt.append((item, (first - start).days))
    pa_days = []
    schedule_days = []
    for item, _days in ttt:
        start = enrolled_on(item)
        decision = pa_on(item)
        first = first_on(item)
        if start and decision and decision >= start:
            pa_days.append((decision - start).days)
        if decision and first and first >= decision:
            schedule_days.append((first - decision).days)

    access_approved = []
    for item in hub:
        titles = " ".join((event["title"] or "").lower() for event in item["events"])
        if "prior authorization approved" in titles or "approved on appeal" in titles:
            if item["facts"].get("status") != "Never started":
                access_approved.append(item)
    pa_decided = [item for item in hub if pa_on(item)]
    started = [item for item in hub if item["facts"].get("dose_count")]
    six = []
    on_six = []
    for item in started:
        first = first_on(item)
        if not first:
            continue
        if (as_of_day - first).days < 182:
            continue
        six.append(item)
        if item["facts"].get("status") == "On therapy":
            on_six.append(item)
            continue
        stop = parse_iso(item["facts"].get("stop_date"))
        if stop and (stop - first).days >= 182:
            on_six.append(item)

    reasons: dict[str, int] = defaultdict(int)
    for item in never:
        reasons[(item["facts"].get("stop_reason") or "No reason recorded").capitalize()] += 1
    stops: dict[str, int] = defaultdict(int)
    for item in stopped:
        stops[(item["facts"].get("stop_reason") or "Not recorded").capitalize()] += 1

    by_payer = []
    for name in ("Commercial", "Medicare", "Medicaid"):
        subset = [days for item, days in ttt if item["payer"] == name]
        by_payer.append({"payer": name, "days": _median(subset), "patients": show(len(subset))})

    docs: dict[str, list] = defaultdict(list)
    for item in treated:
        docs[item["doctor_id"] or item["prescriber"]].append(item)
    prescribers = []
    for key, items in docs.items():
        days = []
        for item in items:
            start = enrolled_on(item)
            first = first_on(item)
            if start and first and first >= start:
                days.append((first - start).days)
        side = sum(1 for item in items if "side effect" in (item["facts"].get("stop_reason") or "").lower())
        sample = items[0]
        prescribers.append(
            {
                "doctor_id": sample["doctor_id"],
                "name": sample["prescriber"],
                "patients": show(len(items)),
                "median_days": _median(days),
                "side_effect_stops": show(side),
            }
        )
    prescribers.sort(key=lambda item: (-(item["patients"] if isinstance(item["patients"], int) else -1), item["name"]))

    states: dict[str, list] = defaultdict(list)
    for item in cohort:
        states[item["state"]].append(item)
    state_rows = []
    for name, items in sorted(states.items(), key=lambda pair: -len(pair[1])):
        outside_n = sum(1 for item in items if item["facts"].get("dose_count") and "hub" not in item["sources"])
        state_rows.append({"state": name, "patients": show(len(items)), "outside_hub": show(outside_n)})

    curves = []
    for brand_name in ("Brand A", "Brand B", "Brand C"):
        if brand and brand != brand_name:
            continue
        pairs = []
        for item in treated:
            if item["brand"] != brand_name:
                continue
            first = first_on(item)
            if not first:
                continue
            if item["facts"].get("status") == "Stopped" and item["facts"].get("stop_date"):
                stop = parse_iso(item["facts"]["stop_date"])
                if stop:
                    pairs.append(((stop - first).days, True))
                    continue
            pairs.append(((as_of_day - first).days, False))
        points = _kaplan(pairs)
        product = product_by_brand(brand_name) or {}
        curves.append(
            {
                "brand": brand_name,
                "description": product.get("description"),
                "points": points,
                "at_6_months": round(_at(points, 182), 4),
            }
        )

    funnel = [
        {"key": "enrolled", "label": "Enrolled in hub", "count": show(len(hub))},
        {"key": "decision", "label": "Prior authorization decision", "count": show(len(pa_decided))},
        {"key": "approved", "label": "Access approved", "count": show(len(access_approved))},
        {"key": "first", "label": "First dose", "count": show(len(started))},
        {"key": "six", "label": "On therapy at 6 months", "count": show(len(on_six)), "denominator": show(len(six))},
    ]
    journeys = [
        {
            "id": item["id"],
            "brand": item["brand"],
            "payer": item["payer"],
            "sources": item["sources"],
            "linked_by": ", ".join(item["layers"]) or "First record",
            "status": item["facts"].get("status"),
            "prescriber": item["prescriber"],
            "doctor_id": item["doctor_id"],
            "stop_reason": item["facts"].get("stop_reason") or "",
            "delayed": bool(item["facts"].get("delays")),
            "in_hub": "hub" in item["sources"],
            "dispensed": bool(item["dispensed"]),
        }
        for item in cohort
    ]
    return {
        "as_of": as_of,
        "small_cell_min": minimum,
        "banner": "Small-cell rule off for synthetic demo data" if minimum == 0 else None,
        "brand": brand or "all",
        "payer": payer or "all",
        "kpis": {
            "linked_journeys": show(len(multi)),
            "patients": show(len(cohort)),
            "median_days_to_first_dose": _median([days for _, days in ttt]),
            "never_started": show(len(never)),
            "never_started_pct": _pct(len(never), len(hub)),
            "hub_patients": show(len(hub)),
            "on_therapy_6_months_pct": _pct(len(on_six), len(six)),
            "on_therapy_6_months": show(len(on_six)),
            "started_6_months_ago": show(len(six)),
            "dose_delay_pct": _pct(len(delays), len(treated)),
            "dose_delays": show(len(delays)),
            "treated": show(len(treated)),
            "outside_hub_pct": _pct(len(outside), len(treated)),
            "outside_hub": show(len(outside)),
            "discontinued": show(len(discontinued)),
            "dispensed": show(len(dispensed)),
            "discontinuation_pct": _pct(len(discontinued), len(dispensed)),
        },
        "funnel": funnel,
        "never_reasons": [{"label": label, "count": show(count)} for label, count in sorted(reasons.items(), key=lambda pair: -pair[1])],
        "time_steps": [
            {"label": "Enrollment to prior authorization", "days": _median(pa_days)},
            {"label": "Prior authorization to first dose", "days": _median(schedule_days)},
            {"label": "Enrollment to first dose", "days": _median([days for _, days in ttt])},
        ],
        "days_by_payer": by_payer,
        "survival": curves,
        "stops": [{"label": label, "count": show(count)} for label, count in sorted(stops.items(), key=lambda pair: -pair[1])],
        "delay_causes": [{"label": "Gap longer than the days supplied plus 7 days", "count": show(len(delays))}] if delays else [],
        "prescribers": prescribers,
        "states": state_rows,
        "linking": {
            "full_journeys": show(len(multi)),
            "hub_patients": show(len(hub)),
            "treated": show(len(treated)),
        },
        "journeys": journeys,
    }


def _pct(part: int, whole: int) -> int:
    if not whole:
        return 0
    return round(100 * part / whole)
