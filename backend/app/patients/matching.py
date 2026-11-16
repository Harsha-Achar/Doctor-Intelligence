"""Layers 1–3. Program IDs, then scores for groups that still have one source."""

from __future__ import annotations

from datetime import date

from app.patients.config import AUTO_MIN, LONE_RUNNER_UP, MARGIN, REVIEW_MIN
from app.patients.scoring import score_pair

SOURCE_ORDER = {"pharmacy": 0, "claims": 1, "hub": 2}


class Record:
    def __init__(self, row: dict) -> None:
        self.id = row["id"]
        self.ref = row["ref"]
        self.source = row["source"]
        self.vendor_patient_id = row["vendor_patient_id"]
        self.hub_case_ids = set(row.get("hub_case_ids") or [])
        self.copay_card_ids = set(row.get("copay_card_ids") or [])
        self.birth_year = row.get("birth_year")
        self.sex = row.get("sex")
        self.zip3 = row.get("zip3")
        self.prescriber_npi = row.get("prescriber_npi") or ""
        self.prescriber_name = row.get("prescriber_name") or "Unknown prescriber"
        self.brand = row.get("brand")
        self.payer_type = row.get("payer_type") or ""
        self.dates = list(row.get("dates") or [])
        self.parent = self.id
        self.layer: str | None = None
        self.reason: str | None = None
        self.score: int | None = None
        self.score_items: list | None = None

    def first_date_sort(self) -> date:
        return min(self.dates) if self.dates else date.max

    def as_score(self) -> dict:
        return {
            "source": self.source,
            "sex": self.sex,
            "birth_year": self.birth_year,
            "zip3": self.zip3,
            "prescriber_npi": self.prescriber_npi,
            "prescriber_name": self.prescriber_name,
            "brand": self.brand,
            "payer_type": self.payer_type,
            "dates": self.dates,
        }


def find(records: dict[int, Record], record_id: int) -> int:
    record = records[record_id]
    if record.parent != record.id:
        record.parent = find(records, record.parent)
    return record.parent


def union(records: dict[int, Record], left: int, right: int) -> None:
    a, b = find(records, left), find(records, right)
    if a != b:
        records[b].parent = a


def groups(records: dict[int, Record]) -> dict[int, list[Record]]:
    out: dict[int, list[Record]] = {}
    for record in records.values():
        out.setdefault(find(records, record.id), []).append(record)
    return out


def _link_program(records: dict[int, Record], members: list[Record], reason: str) -> None:
    if len(members) < 2:
        return
    anchor = members[0]
    for other in members[1:]:
        if anchor.sex != other.sex:
            continue
        if anchor.birth_year is None or other.birth_year is None:
            continue
        if abs(int(anchor.birth_year) - int(other.birth_year)) > 1:
            continue
        union(records, anchor.id, other.id)
        for record in (anchor, other):
            if not record.layer:
                record.layer = "program_id"
                record.reason = reason


def layer_program_ids(records: dict[int, Record]) -> int:
    buckets: dict[str, list[Record]] = {}
    for record in records.values():
        for case_id in record.hub_case_ids:
            buckets.setdefault(f"hub|{case_id}", []).append(record)
        for card_id in record.copay_card_ids:
            buckets.setdefault(f"copay|{card_id}", []).append(record)
    for key, members in buckets.items():
        kind = "Hub case ID" if key.startswith("hub|") else "Copay card ID"
        _link_program(records, members, kind)
    return sum(1 for record in records.values() if record.layer == "program_id")


def _blocked(left: list[Record], right: list[Record]) -> bool:
    npis_l = {item.prescriber_npi for item in left if item.prescriber_npi}
    npis_r = {item.prescriber_npi for item in right if item.prescriber_npi}
    if npis_l & npis_r:
        return True
    keys_l = {(item.birth_year, item.zip3) for item in left if item.birth_year and item.zip3}
    keys_r = {(item.birth_year, item.zip3) for item in right if item.birth_year and item.zip3}
    return bool(keys_l & keys_r)


def _best_pair(incoming: list[Record], candidate: list[Record]) -> dict | None:
    has_hub = any(record.source == "hub" for record in candidate)
    best = None
    for left in incoming:
        for right in candidate:
            scored = score_pair(
                left.as_score(),
                right.as_score(),
                incoming_is_hub=left.source == "hub",
                candidate_has_hub=has_hub,
            )
            if scored is None:
                continue
            if best is None or scored["score"] > best["score"]:
                best = scored
    return best


def _single_source(members: list[Record]) -> bool:
    return bool(members) and all(record.source == members[0].source for record in members)


def layer_scores(records: dict[int, Record]) -> dict[int, list[dict]]:
    """Review decisions keyed by the incoming component root."""
    initial = groups(records)
    todo = sorted(
        (root for root, members in initial.items() if _single_source(members)),
        key=lambda root: (
            SOURCE_ORDER[initial[root][0].source],
            initial[root][0].first_date_sort(),
            initial[root][0].ref,
        ),
    )
    reviews: dict[int, list[dict]] = {}
    for root0 in todo:
        current = groups(records)
        root = find(records, root0)
        members = current.get(root)
        if not members or not _single_source(members):
            continue
        if root in reviews:
            continue
        candidates = []
        for other_root, other in current.items():
            if other_root == root or not _blocked(members, other):
                continue
            best = _best_pair(members, other)
            if best is None or best["score"] <= LONE_RUNNER_UP:
                continue
            candidates.append({"root": other_root, "score": best["score"], "items": best["items"]})
        candidates.sort(key=lambda item: (-item["score"], item["root"]))
        top = candidates[:3]
        if not top:
            continue
        best_score = top[0]["score"]
        runner = top[1]["score"] if len(top) > 1 else LONE_RUNNER_UP
        margin = best_score - runner
        if best_score >= AUTO_MIN and margin >= MARGIN:
            union(records, members[0].id, top[0]["root"])
            for record in members:
                if not record.layer:
                    record.layer = "score"
                    record.reason = f"Score {best_score:+d}"
                    record.score = best_score
                    record.score_items = top[0]["items"]
            continue
        if best_score >= REVIEW_MIN:
            reviews[root] = top

    for _ in range(5):
        changed = False
        review_roots = {find(records, root) for root in reviews}
        for root in list(reviews):
            kept = []
            seen = set()
            for candidate in reviews[root]:
                resolved = find(records, candidate["root"])
                if resolved in review_roots or resolved in seen:
                    continue
                seen.add(resolved)
                kept.append({"root": resolved, "score": candidate["score"], "items": candidate["items"]})
            if [c["root"] for c in kept] != [c["root"] for c in reviews[root]] or len(kept) != len(reviews[root]):
                reviews[root] = kept
                changed = True
            if not kept or kept[0]["score"] < REVIEW_MIN:
                reviews.pop(root, None)
                changed = True
        if not changed:
            break
    return reviews


def finish_layers(records: dict[int, Record], review_roots: set[int]) -> None:
    for record in records.values():
        if find(records, record.id) in review_roots:
            continue
        if not record.layer:
            record.layer = "first_record"
            if record.source == "hub":
                record.reason = "Hub enrollment, no therapy records found yet"
            else:
                record.reason = "No other record for this person yet"
