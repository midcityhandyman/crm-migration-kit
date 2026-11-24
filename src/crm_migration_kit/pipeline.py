"""The migration pipeline: load, normalise, drop, dedupe, map, write."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .dedupe import dedupe
from .mapping import Mapping, load_mapping
from .normalize import clean_name, normalize_email, normalize_phone, split_full_name
from .report import Report

CLEANED_NAME = "cleaned_contacts.csv"
REPORT_JSON_NAME = "validation_report.json"
REPORT_MD_NAME = "validation_report.md"


@dataclass(frozen=True)
class Settings:
    default_country_code: str = "1"
    name_similarity: float = 0.82

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            default_country_code=str(env.get("CRM_KIT_DEFAULT_COUNTRY_CODE", "1")).lstrip("+") or "1",
            name_similarity=float(env.get("CRM_KIT_NAME_SIMILARITY", "0.82")),
        )


def read_csv(path: str | Path) -> tuple[list[str], list[tuple[int, dict]]]:
    """Read a CSV into (headers, [(row_number, row)]). Row 1 is the header."""
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = [(number, row) for number, row in enumerate(reader, start=2)]
    return headers, rows


def _canonical_record(row: dict, resolved: dict[str, str], blank_tokens: set[str]) -> dict:
    record: dict[str, str] = {canonical: "" for canonical in resolved.values()}
    for header, canonical in resolved.items():
        value = (row.get(header) or "").strip()
        if value.lower() in blank_tokens:
            value = ""
        if value and not record[canonical]:
            record[canonical] = value
    return record


def process(
    headers: list[str],
    rows: list[tuple[int, dict]],
    mapping: Mapping,
    settings: Settings | None = None,
) -> tuple[list[dict], Report]:
    """Run the whole pipeline in memory. Returns (target rows, report)."""
    settings = settings or Settings()
    report = Report(rows_read=len(rows))
    resolved, report.unmapped_columns = mapping.resolve_headers(headers)
    blank_tokens = set(mapping.blank_tokens)

    records: list[dict] = []
    for number, row in rows:
        record = _canonical_record(row, resolved, blank_tokens)
        if not any(record.values()):
            report.add_drop(number, "empty_row", "No mapped column has a value.")
            continue

        # Names: split a full name when first and last are missing.
        record["first_name"] = clean_name(record.get("first_name"))
        record["last_name"] = clean_name(record.get("last_name"))
        if record.get("full_name") and not (record["first_name"] or record["last_name"]):
            record["first_name"], record["last_name"] = split_full_name(record["full_name"])

        if "phone" in record:
            raw = record["phone"]
            phone = normalize_phone(raw, settings.default_country_code)
            record["phone"], record["phone_ext"] = phone.value, phone.extension
            if phone.issue:
                report.add_flag(number, phone.issue, f"Could not read phone '{raw}', left blank.")
        if "email" in record:
            raw = record["email"]
            email = normalize_email(raw)
            record["email"] = email.value
            if email.issue == "invalid_email":
                report.add_flag(number, "invalid_email", f"Could not read email '{raw}', left blank.")
            elif email.issue == "email_repaired":
                report.add_flag(number, "email_repaired", f"Email '{raw}' repaired to '{email.value}', please confirm.")

        if mapping.require_any and not any(record.get(name) for name in mapping.require_any):
            needed = " or ".join(mapping.require_any)
            report.add_drop(number, "no_contact_method", f"No valid {needed} after normalisation.")
            continue

        record["_row"] = number
        records.append(record)

    result = dedupe(
        records,
        name_threshold=settings.name_similarity,
        ignore_plus_tags=mapping.ignore_email_plus_tags,
    )
    report.flags.extend(result.flags)
    for group in result.merges:
        report.merges.append(
            {
                "kept_row": group.kept_row,
                "merged_rows": group.merged_rows,
                "rules": [asdict(link) for link in group.links],
                "conflicts": group.conflicts,
            }
        )

    target_rows: list[dict] = []
    for record in result.records:
        out: dict[str, str] = {}
        for target_field in mapping.fields:
            value, issues = target_field.apply(record)
            out[target_field.name] = value
            for code, detail in issues:
                report.add_flag(record["_row"], code, detail)
        if mapping.audit_column:
            out[mapping.audit_column] = " ".join(str(r) for r in record["_rows"])
        target_rows.append(out)

    report.rows_written = len(target_rows)
    return target_rows, report


def run_migration(
    input_path: str | Path,
    mapping_path: str | Path,
    out_dir: str | Path,
    settings: Settings | None = None,
) -> Report:
    """Run the pipeline on files and write the cleaned CSV plus both reports."""
    mapping = load_mapping(mapping_path)
    headers, rows = read_csv(input_path)
    target_rows, report = process(headers, rows, mapping, settings)
    report.input_file = Path(input_path).as_posix()
    report.mapping_file = Path(mapping_path).as_posix()

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / CLEANED_NAME, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=mapping.target_headers(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(target_rows)
    with open(out / REPORT_JSON_NAME, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report.to_dict(), handle, indent=2)
        handle.write("\n")
    with open(out / REPORT_MD_NAME, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(report.to_markdown())
    return report
