"""Duplicate detection with rules a person can read back.

Rules, applied in order:

1. email_exact            same email address                      -> merge
2. phone_and_name         same phone and similar names            -> merge
3. phone_name_missing     same phone and one record has no name   -> merge
                          (only when the phone belongs to one name)
4. shared_phone           same phone but different names          -> flag only
5. name_and_company       same name and company, nothing else     -> flag only

Merges are transitive (A=B and B=C puts all three in one group). Every merge
keeps the list of rule hits that produced it and every field conflict that
the survivor rule had to settle.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from .normalize import email_match_key, name_key, name_similarity

Record = dict  # canonical field -> str, plus "_row" (source row number)


@dataclass
class MatchLink:
    rule: str
    rows: tuple[int, int]
    reason: str


@dataclass
class MergeGroup:
    kept_row: int
    merged_rows: list[int]
    links: list[MatchLink]
    conflicts: list[dict] = field(default_factory=list)


@dataclass
class DedupeResult:
    records: list[Record]  # survivors, each with "_rows" listing its sources
    merges: list[MergeGroup]
    flags: list[dict]  # {"row", "code", "detail"}


class _UnionFind:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _data_fields(record: Record) -> list[str]:
    return [k for k in record if not k.startswith("_")]


def _filled(record: Record) -> int:
    return sum(1 for k in _data_fields(record) if record[k])


def merge_records(group: list[Record]) -> tuple[Record, list[dict]]:
    """Merge a group into one survivor.

    The record with the most filled fields wins (earliest row breaks ties).
    Its blanks are filled from the others in row order. Any non blank value
    that disagrees with the kept one is returned as a conflict.
    """
    ordered = sorted(group, key=lambda r: r["_row"])
    primary = max(ordered, key=lambda r: (_filled(r), -r["_row"]))
    merged = dict(primary)
    conflicts: list[dict] = []
    fields = list(dict.fromkeys(k for r in ordered for k in _data_fields(r)))
    for name in fields:
        for other in ordered:
            if other is primary:
                continue
            value = other.get(name, "")
            if not value:
                continue
            kept = merged.get(name, "")
            if not kept:
                merged[name] = value
            elif value.strip().lower() != kept.strip().lower():
                conflicts.append(
                    {"field": name, "kept": kept, "discarded": value, "from_row": other["_row"]}
                )
    merged["_rows"] = [r["_row"] for r in ordered]
    return merged, conflicts


def dedupe(
    records: list[Record],
    *,
    name_threshold: float = 0.82,
    ignore_plus_tags: bool = True,
) -> DedupeResult:
    """Find duplicates in normalised records and merge them."""
    by_row = {r["_row"]: r for r in records}
    uf = _UnionFind(by_row)
    links: list[MatchLink] = []
    pending_flags: list[tuple[int, int, str, str]] = []  # row_a, row_b, code, detail

    # Rule 1: same email.
    by_email: dict[str, list[Record]] = defaultdict(list)
    for rec in records:
        key = email_match_key(rec.get("email", ""), ignore_plus_tags)
        if key:
            by_email[key].append(rec)
    for key, group in by_email.items():
        for other in group[1:]:
            uf.union(group[0]["_row"], other["_row"])
            links.append(
                MatchLink("email_exact", (group[0]["_row"], other["_row"]), f"same email address {key}")
            )

    # Rules 2 to 4: same phone, decided by the names.
    by_phone: dict[str, list[Record]] = defaultdict(list)
    for rec in records:
        if rec.get("phone"):
            by_phone[rec["phone"]].append(rec)
    for phone, group in by_phone.items():
        named = [r for r in group if name_key(r.get("first_name", ""), r.get("last_name", ""))]
        nameless = [r for r in group if r not in named]
        for a, b in combinations(named, 2):
            if uf.find(a["_row"]) == uf.find(b["_row"]):
                continue
            rows = (a["_row"], b["_row"])
            score = name_similarity(a["first_name"], a["last_name"], b["first_name"], b["last_name"])
            if score >= name_threshold:
                uf.union(*rows)
                links.append(
                    MatchLink(
                        "phone_and_name", rows,
                        f"same phone {phone} and name similarity {score:.2f} (threshold {name_threshold:.2f})",
                    )
                )
            else:
                pending_flags.append(
                    (*rows, "shared_phone",
                     f"same phone {phone} but names differ (similarity {score:.2f}), not merged")
                )
        # A record with no name merges only when the phone points at one person.
        # If the named records on this phone are still separate people, merging
        # the nameless one into each of them would join them all together.
        for rec in nameless:
            people: dict[int, Record] = {}
            for other in named:
                people.setdefault(uf.find(other["_row"]), other)
            if uf.find(rec["_row"]) in people:
                continue
            if len(people) > 1:
                for other in people.values():
                    pending_flags.append(
                        (*sorted((other["_row"], rec["_row"])), "shared_phone",
                         f"same phone {phone}, one record has no name and the phone is used "
                         "by more than one name, not merged")
                    )
                continue
            if people:
                other = next(iter(people.values()))
                reason = f"same phone {phone} and row {rec['_row']} has no name"
            else:
                other = nameless[0]
                if other is rec or uf.find(other["_row"]) == uf.find(rec["_row"]):
                    continue
                reason = f"same phone {phone} and neither record has a name"
            rows = tuple(sorted((other["_row"], rec["_row"])))
            uf.union(*rows)
            links.append(MatchLink("phone_name_missing", rows, reason))

    # Rule 5: same name and company. Too weak to merge on its own.
    by_identity: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for rec in records:
        person = name_key(rec.get("first_name", ""), rec.get("last_name", ""))
        company = re.sub(r"[^a-z0-9]", "", rec.get("company", "").lower())
        if person and company:
            by_identity[(person, company)].append(rec)
    for group in by_identity.values():
        for a, b in combinations(group, 2):
            pending_flags.append(
                (a["_row"], b["_row"], "possible_duplicate",
                 "same name and company but no shared email or phone, not merged")
            )

    # Build the merge groups.
    clusters: dict[int, list[Record]] = defaultdict(list)
    for rec in records:
        clusters[uf.find(rec["_row"])].append(rec)

    survivors: list[Record] = []
    merges: list[MergeGroup] = []
    survivor_of: dict[int, int] = {}
    for root in sorted(clusters):
        group = clusters[root]
        if len(group) == 1:
            solo = dict(group[0])
            solo["_rows"] = [solo["_row"]]
            survivors.append(solo)
            survivor_of[root] = solo["_row"]
            continue
        merged, conflicts = merge_records(group)
        survivors.append(merged)
        survivor_of[root] = merged["_row"]
        merges.append(
            MergeGroup(
                kept_row=merged["_row"],
                merged_rows=[r for r in merged["_rows"] if r != merged["_row"]],
                links=[ln for ln in links if uf.find(ln.rows[0]) == root],
                conflicts=conflicts,
            )
        )
    survivors.sort(key=lambda r: min(r["_rows"]))

    # Flags only apply to pairs that did not end up merged anyway.
    flags: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for row_a, row_b, code, detail in pending_flags:
        root_a, root_b = uf.find(row_a), uf.find(row_b)
        if root_a == root_b or (root_a, root_b) in seen:
            continue
        seen.add((root_a, root_b))
        keep_a, keep_b = survivor_of[root_a], survivor_of[root_b]
        flags.append({"row": keep_a, "code": code, "detail": f"{detail} (other row {keep_b})"})
        flags.append({"row": keep_b, "code": code, "detail": f"{detail} (other row {keep_a})"})

    return DedupeResult(records=survivors, merges=merges, flags=flags)
