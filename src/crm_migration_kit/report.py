"""Validation report: what was dropped, merged and flagged, and why."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Report:
    input_file: str = ""
    mapping_file: str = ""
    rows_read: int = 0
    rows_written: int = 0
    dropped: list[dict] = field(default_factory=list)  # {"row", "reason", "detail"}
    merges: list[dict] = field(default_factory=list)  # {"kept_row", "merged_rows", "rules", "conflicts"}
    flags: list[dict] = field(default_factory=list)  # {"row", "code", "detail"}
    unmapped_columns: list[str] = field(default_factory=list)

    def add_flag(self, row: int, code: str, detail: str) -> None:
        self.flags.append({"row": row, "code": code, "detail": detail})

    def add_drop(self, row: int, reason: str, detail: str) -> None:
        self.dropped.append({"row": row, "reason": reason, "detail": detail})

    @property
    def rows_merged_away(self) -> int:
        return sum(len(m["merged_rows"]) for m in self.merges)

    def summary(self) -> dict:
        return {
            "rows_read": self.rows_read,
            "rows_dropped": len(self.dropped),
            "rows_merged_away": self.rows_merged_away,
            "merge_groups": len(self.merges),
            "rows_flagged": len({f["row"] for f in self.flags}),
            "flags_total": len(self.flags),
            "rows_written": self.rows_written,
            "balanced": self.rows_read == len(self.dropped) + self.rows_merged_away + self.rows_written,
        }

    def to_dict(self) -> dict:
        return {
            "input_file": self.input_file,
            "mapping_file": self.mapping_file,
            "summary": self.summary(),
            "drop_reasons": dict(sorted(Counter(d["reason"] for d in self.dropped).items())),
            "flag_codes": dict(sorted(Counter(f["code"] for f in self.flags).items())),
            "unmapped_columns": self.unmapped_columns,
            "dropped": self.dropped,
            "merges": self.merges,
            "flags": sorted(self.flags, key=lambda f: (f["row"], f["code"])),
        }

    def to_markdown(self) -> str:
        data = self.to_dict()
        s = data["summary"]
        lines = [
            "# Validation report",
            "",
            f"- Input: `{self.input_file}`",
            f"- Mapping: `{self.mapping_file}`",
            "",
            "## Summary",
            "",
            "| Measure | Count |",
            "| --- | ---: |",
            f"| Rows read | {s['rows_read']} |",
            f"| Rows dropped | {s['rows_dropped']} |",
            f"| Rows merged into another row | {s['rows_merged_away']} |",
            f"| Merge groups | {s['merge_groups']} |",
            f"| Rows written | {s['rows_written']} |",
            f"| Rows flagged for review | {s['rows_flagged']} |",
            "",
            "Check: read = dropped + merged + written is "
            + ("true." if s["balanced"] else "FALSE, investigate before loading."),
            "",
            "## Dropped rows",
            "",
        ]
        if not self.dropped:
            lines.append("None.")
        for d in self.dropped:
            lines.append(f"- Row {d['row']}: {d['reason']}. {d['detail']}")
        lines += ["", "## Merged rows", ""]
        if not self.merges:
            lines.append("None.")
        for m in self.merges:
            merged = ", ".join(str(r) for r in m["merged_rows"])
            lines.append(f"- Kept row {m['kept_row']}, merged in row(s) {merged}")
            for rule in m["rules"]:
                a, b = rule["rows"]
                lines.append(f"  - {rule['rule']}: rows {a} and {b}, {rule['reason']}")
            for c in m["conflicts"]:
                lines.append(
                    f"  - conflict on {c['field']}: kept '{c['kept']}', "
                    f"discarded '{c['discarded']}' from row {c['from_row']}"
                )
        lines += ["", "## Flagged rows", ""]
        if not data["flags"]:
            lines.append("None.")
        for f in data["flags"]:
            lines.append(f"- Row {f['row']}: {f['code']}. {f['detail']}")
        if self.unmapped_columns:
            lines += ["", "## Source columns not in the mapping (ignored)", ""]
            lines += [f"- {name}" for name in self.unmapped_columns]
        return "\n".join(lines) + "\n"
