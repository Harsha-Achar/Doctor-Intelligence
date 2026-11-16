"""Compare linked patients to the answer key. The matcher never imports this module."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict

from app.patients.config import answer_key_path
from app.patients.db import DB


def load_answer_key() -> list[dict] | None:
    path = answer_key_path()
    if not path.exists():
        return None
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def quality() -> dict | None:
    key = load_answer_key()
    if not key:
        return None
    truth: dict[tuple[str, str], dict] = {}
    for row in key:
        truth[(row["source"], row["vendor_patient_id"])] = row
    with DB() as db:
        linked = db.query(
            """
            SELECT r.source, r.vendor_patient_id, p.daiichi_patient_id
            FROM pt_link l
            JOIN pt_record r ON r.id = l.record_id
            JOIN pt_patient p ON p.id = l.patient_id
            WHERE p.retired_into IS NULL
            """
        )
        reviews = db.query(
            """
            SELECT r.source, r.vendor_patient_id, rv.top3_json, rv.status
            FROM pt_review rv
            JOIN pt_record r ON r.id = rv.record_id
            WHERE rv.status IN ('open', 'deferred')
            """
        )
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in linked:
        groups[row["daiichi_patient_id"]].append((row["source"], row["vendor_patient_id"]))
    wrong = 0
    correct_links = 0
    keyed_links = 0
    for members in groups.values():
        labels = [truth[item]["truth_id"] for item in members if item in truth]
        if len(set(labels)) > 1:
            wrong += 1
        if not labels:
            continue
        mode = Counter(labels).most_common(1)[0][0]
        for label in labels:
            keyed_links += 1
            if label == mode:
                correct_links += 1
    open_keys = {(row["source"], row["vendor_patient_id"]) for row in reviews}
    expected_review = { (row["source"], row["vendor_patient_id"]): row["truth_id"] for row in key if row["role"] == "review" }
    top_right = 0
    from app.patients.db import loads

    for row in reviews:
        key_row = expected_review.get((row["source"], row["vendor_patient_id"]))
        top = loads(row["top3_json"], [])
        if not key_row or not top or not top[0].get("daiichi_patient_id"):
            continue
        suggested = top[0]["daiichi_patient_id"]
        member_labels = set()
        for daiichi, members in groups.items():
            if daiichi == suggested:
                member_labels = {truth[item]["truth_id"] for item in members if item in truth}
        if key_row in member_labels:
            top_right += 1
    return {
        "wrong_merges": wrong,
        "open_reviews": len(open_keys),
        "expected_reviews": len(expected_review),
        "top_suggestion_correct": top_right,
        "patients": len(groups),
        "link_correct_pct": round(100 * correct_links / keyed_links, 1) if keyed_links else 100,
    }
