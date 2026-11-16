"""Patient summaries and review reasoning. Templates stand in when Azure OpenAI is not configured."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.patients.textutil import fmt_date

DATE_RE = re.compile(r"\b\d{1,2} [A-Z][a-z]{2} \d{4}\b")
REF_RE = re.compile(r"\b(?:HUB|SP|CLM)-\d+\b")


def facts_hash(facts: dict) -> str:
    payload = json.dumps(facts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dates_in(facts: dict) -> list[str]:
    found = []
    blob = json.dumps(facts, default=str)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
            label = fmt_date(value[:10])
            if label:
                found.append(label)

    walk(facts)
    # Keep JSON dates discoverable as formatted text for the validator.
    facts_dates = list(dict.fromkeys(found))
    if facts_dates and "date_labels" not in blob:
        pass
    return facts_dates


def prepare_facts(facts: dict) -> dict:
    labels = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10] if len(value) >= 10 else ""):
            labels.append(fmt_date(value[:10]))

    walk(facts)
    facts = dict(facts)
    facts["date_labels"] = list(dict.fromkeys(labels))
    return facts


def output_matches_facts(text: str, facts: dict) -> bool:
    blob = json.dumps(facts, default=str)
    for label in DATE_RE.findall(text or ""):
        if label not in blob and label not in set(facts.get("date_labels") or []):
            return False
    stripped = DATE_RE.sub(" ", text or "")
    for match in re.finditer(r"\b\d+(?:\.\d+)?\b", stripped):
        token = match.group(0)
        if re.search(rf"(?<!\d){re.escape(token)}(?!\d)", blob) is None:
            return False
    return True


def template_summary(facts: dict) -> dict:
    status = facts.get("status") or ""
    therapy = facts.get("therapy") or {}
    brand = therapy.get("brand") or "therapy"
    description = therapy.get("description") or ""
    unit = therapy.get("unit") or ""
    refs = " ".join(facts.get("record_refs") or [])
    first = fmt_date(facts.get("first_dose"))
    last = fmt_date(facts.get("last_dose"))
    nxt = fmt_date(facts.get("next_dose"))
    as_of = fmt_date(facts.get("as_of"))
    count = facts.get("dose_count") or 0
    qty = facts.get("quantity")
    if status == "On therapy":
        overdue = " It is overdue." if facts.get("overdue") else ""
        status_line = f"On therapy since {first}. Last dose on {last}; next dose due {nxt}.{overdue}"
    elif status == "Stopped":
        dose_word = "dose" if count == 1 else "doses"
        status_line = f"Stopped on {fmt_date(facts.get('stop_date'))} after {count} {dose_word} ({first} – {last}). {facts.get('stop_reason') or ''}".strip()
    elif status == "Never started":
        status_line = f"Never started. The hub closed the case on {fmt_date(facts.get('stop_date'))}: {facts.get('stop_reason') or 'no reason recorded'}."
    elif status == "Waiting to start":
        enrolled = ""
        for step in facts.get("access") or []:
            if "enrolled" in (step.get("title") or "").lower():
                enrolled = fmt_date(step.get("date"))
                break
        status_line = f"Waiting to start. Enrolled on {enrolled}. No dose yet." if enrolled else "Waiting to start. No dose yet."
    elif status == "Claims only":
        status_line = f"Seen in claims only. {count} doses from {first} to {last}."
        if nxt:
            status_line += f" Next dose due {nxt}."
    else:
        status_line = status or "No status recorded."
    if as_of:
        status_line = status_line.rstrip(".") + f". Data as of {as_of}."
    if refs:
        status_line = f"{status_line} {refs}".strip()

    reduction = facts.get("reduction")
    delays = facts.get("delays") or []
    if count:
        dose = f"Dose: {qty} × {unit} of {brand} ({description}). {count} doses received."
        if reduction:
            dose += f" Dose reduced from {reduction.get('from')} to {reduction.get('to')} on {fmt_date(reduction.get('date'))}."
        if delays:
            bits = [f"{item.get('days_late')} days late on {fmt_date(item.get('date'))}" for item in delays]
            dose += " Delayed: " + "; ".join(bits) + "."
        else:
            dose += " Doses are on schedule except where a note says otherwise."
    else:
        dose = "Dose: no dispense or claim is linked yet."

    pharmacy = facts.get("pharmacy")
    if pharmacy:
        previous = facts.get("previous_pharmacy")
        if previous and previous != pharmacy:
            pharmacy_line = f"Pharmacy: {pharmacy}. Switched from {previous} on {fmt_date(facts.get('switch_date'))}."
        else:
            pharmacy_line = f"Pharmacy: {pharmacy}. Same pharmacy throughout."
    else:
        pharmacy_line = "Pharmacy: none linked."

    access_steps = facts.get("access") or []
    if access_steps:
        parts = [f"{step.get('title')} {fmt_date(step.get('date'))}".strip() for step in access_steps]
        access = "Getting access: " + "; ".join(parts) + "."
    else:
        access = "Getting access: no hub enrollment is linked."

    watch = facts.get("watch") or []
    watch_line = "Watch: " + "; ".join(watch) + "." if watch else "Watch: nothing outstanding in the linked records."
    paragraphs = [status_line, dose, pharmacy_line, access, watch_line]
    return {
        "status_line": status_line,
        "dose": dose,
        "pharmacy": pharmacy_line,
        "getting_access": access,
        "watch": watch_line,
        "paragraphs": paragraphs,
        "template": True,
    }


def template_reasoning(payload: dict) -> dict:
    top = payload.get("candidates") or []
    best = top[0] if top else {}
    others = top[1:]
    agrees = best.get("agrees") or []
    differs = best.get("differs") or []
    lead = best.get("patient_id") or "the nearest patient"
    margin = best.get("margin")
    recommendation = f"A person should decide. The nearest patient is {lead}."
    if margin is not None and best.get("suggested"):
        recommendation = f"Assign to {lead}. It leads the next candidate by {margin} points. The model only recommends."
    why = payload.get("why_not_auto") or "The score is below the automatic link threshold, or two patients are too close."
    why_others = "; ".join(
        f"{item.get('patient_id')} scores {item.get('score')}" for item in others
    ) or "No other candidate is in blocking distance."
    return {
        "recommendation": recommendation,
        "why_not_auto": why,
        "agrees": agrees,
        "differs": differs,
        "why_not_others": why_others,
        "what_happens_next": "Assigning adds this record to the Daiichi patient and their journey. It can be undone from the patient's history.",
        "template": True,
    }


def _llm_json(system: str, user: str) -> dict | None:
    from app.ai.provider import build_llm_client
    from app.core.settings import get_settings

    settings = get_settings()
    if settings.analysis_mode != "azure" or not settings.ai_ready:
        return None
    import asyncio

    client = build_llm_client(settings)

    def run_call() -> str:
        async def call() -> str:
            result = await client.complete_json(system=system, user=user, request_id="patient-analytics")
            return result.content or ""

        return asyncio.run(call())

    try:
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False
        if in_loop:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=1) as pool:
                content = pool.submit(run_call).result()
        else:
            content = run_call()
    except Exception:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def write_summary(facts: dict) -> tuple[dict, str]:
    facts = prepare_facts(facts)
    system = (
        "You write a short de-identified patient summary as JSON. "
        "Use only the facts. Every date must look like 12 Feb 2026 and must appear in date_labels. "
        "Do not invent numbers. Do not include vendor patient IDs, hub case IDs or copay card IDs. "
        "Keys: status_line, dose, pharmacy, getting_access, watch."
    )
    user = json.dumps({"facts": facts}, default=str)
    for _ in range(2):
        parsed = _llm_json(system, user)
        if not parsed:
            break
        text = " ".join(str(parsed.get(key) or "") for key in ("status_line", "dose", "pharmacy", "getting_access", "watch"))
        if output_matches_facts(text, facts):
            paragraphs = [str(parsed.get(key) or "") for key in ("status_line", "dose", "pharmacy", "getting_access", "watch")]
            body = {
                "status_line": paragraphs[0],
                "dose": paragraphs[1],
                "pharmacy": paragraphs[2],
                "getting_access": paragraphs[3],
                "watch": paragraphs[4],
                "paragraphs": paragraphs,
                "template": False,
            }
            from app.core.settings import get_settings

            return body, get_settings().azure_openai_deployment or "azure"
    body = template_summary(facts)
    if not output_matches_facts(" ".join(body["paragraphs"]), facts):
        # Last resort: a sentence that only quotes fact labels.
        labels = ", ".join(facts.get("date_labels") or [])
        body = {
            "status_line": f"{facts.get('status') or 'Patient'}. Dates on record: {labels}.",
            "dose": f"Doses recorded: {facts.get('dose_count') or 0}.",
            "pharmacy": f"Pharmacy: {facts.get('pharmacy') or 'none linked'}.",
            "getting_access": "Getting access is listed in the timeline.",
            "watch": "Watch: " + "; ".join(facts.get("watch") or ["nothing outstanding"]),
            "paragraphs": [],
            "template": True,
        }
        body["paragraphs"] = [
            body["status_line"],
            body["dose"],
            body["pharmacy"],
            body["getting_access"],
            body["watch"],
        ]
    return body, "template"


def write_reasoning(payload: dict) -> dict:
    payload = prepare_facts(payload)
    system = (
        "You explain a patient-matching review as JSON. Recommend only; a person assigns. "
        "Use only the facts. Keys: recommendation, why_not_auto, agrees, differs, why_not_others, what_happens_next. "
        "agrees and differs are arrays of short strings. Do not include vendor patient IDs, hub case IDs or copay card IDs."
    )
    user = json.dumps({"facts": payload}, default=str)
    for _ in range(2):
        parsed = _llm_json(system, user)
        if not parsed:
            break
        text = json.dumps(parsed)
        if output_matches_facts(text, payload):
            parsed["template"] = False
            return parsed
    return template_reasoning(payload)
