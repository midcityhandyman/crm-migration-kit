import csv
import json
from pathlib import Path

from crm_migration_kit.mapping import load_mapping, parse_mapping
from crm_migration_kit.pipeline import Settings, process, read_csv, run_migration

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_data" / "contacts_messy.csv"
MAPPING = ROOT / "sample_data" / "mapping.yaml"


def run_sample(tmp_path):
    report = run_migration(SAMPLE, MAPPING, tmp_path)
    with open(tmp_path / "cleaned_contacts.csv", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return report, rows


def test_sample_counts_balance(tmp_path):
    report, rows = run_sample(tmp_path)
    summary = report.summary()
    assert summary["rows_read"] == 29
    assert summary["rows_dropped"] == 3
    assert summary["rows_merged_away"] == 7
    assert summary["rows_written"] == len(rows) == 19
    assert summary["balanced"] is True


def test_sample_drops_are_explained(tmp_path):
    report, _ = run_sample(tmp_path)
    assert {(d["row"], d["reason"]) for d in report.dropped} == {
        (9, "no_contact_method"), (10, "empty_row"), (19, "no_contact_method")}


def test_sample_merge_and_output_values(tmp_path):
    report, rows = run_sample(tmp_path)
    alex = next(r for r in rows if r["Email"] == "alex.sample@example.com")
    assert alex["SourceRows"] == "2 3 4"
    assert alex["Phone"] == "+15555550101"
    assert alex["DisplayName"] == "Alex Sample"
    assert alex["LeadSource"] == "Website"
    jordan = next(r for r in rows if r["LastName"] == "Testerson")
    assert (jordan["FirstName"], jordan["PhoneExtension"], jordan["SourceRows"]) == ("Jordan", "204", "5 6")
    pat = next(r for r in rows if r["LastName"] == "Sampleton")
    assert (pat["FirstName"], pat["Email"], pat["Phone"]) == ("Pat Q.", "pat.sampleton@example.net", "+15555550106")
    assert sum(1 for r in rows if r["LastName"] == "Mockwell") == 2  # shared phone, not merged
    assert all(r["ImportBatch"] == "sample-batch-01" for r in rows)
    emails = [r["Email"] for r in rows if r["Email"]]
    assert len(emails) == len(set(emails))
    merged_rows = sorted(row for m in report.merges for row in m["merged_rows"])
    assert len(merged_rows) == 7 and all(m["rules"] for m in report.merges)


def test_sample_flags(tmp_path):
    report, _ = run_sample(tmp_path)
    flags = {(f["row"], f["code"]) for f in report.flags}
    assert flags == {
        (7, "invalid_email"), (8, "invalid_phone"), (11, "shared_phone"), (12, "shared_phone"),
        (16, "email_repaired"), (17, "possible_duplicate"), (18, "possible_duplicate"),
        (22, "unmapped_value"), (23, "missing_required"),
    }
    assert report.unmapped_columns == ["Legacy ID"]


def test_report_files_are_written_and_consistent(tmp_path):
    report, _ = run_sample(tmp_path)
    data = json.loads((tmp_path / "validation_report.json").read_text(encoding="utf-8"))
    assert data["summary"] == report.summary()
    assert data["drop_reasons"] == {"empty_row": 1, "no_contact_method": 2}
    markdown = (tmp_path / "validation_report.md").read_text(encoding="utf-8")
    assert "Kept row 5, merged in row(s) 6" in markdown
    assert "read = dropped + merged + written is true" in markdown


def test_run_is_deterministic(tmp_path):
    run_migration(SAMPLE, MAPPING, tmp_path / "a")
    run_migration(SAMPLE, MAPPING, tmp_path / "b")
    for name in ("cleaned_contacts.csv", "validation_report.json", "validation_report.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_bom_and_settings(tmp_path):
    source = tmp_path / "in.csv"
    source.write_bytes("﻿Name,Email,Tel\nAlex Sample,ALEX@EXAMPLE.COM,5555550101\n".encode("utf-8"))
    headers, rows = read_csv(source)
    assert headers == ["Name", "Email", "Tel"]
    mapping = parse_mapping({
        "source_columns": {"full_name": ["Name"], "email": [], "phone": ["Tel"]},
        "target": {"fields": [{"name": "Last", "from": "last_name"}, {"name": "Phone", "from": "phone"}]},
    })
    out, report = process(headers, rows, mapping, Settings(default_country_code="44"))
    assert out == [{"Last": "Sample", "Phone": "+445555550101"}]
    assert report.flags == [] and report.dropped == []


def test_settings_from_env():
    settings = Settings.from_env({"CRM_KIT_DEFAULT_COUNTRY_CODE": "+44", "CRM_KIT_NAME_SIMILARITY": "0.5"})
    assert settings == Settings(default_country_code="44", name_similarity=0.5)
    assert Settings.from_env({}) == Settings()


def test_require_any_can_be_turned_off():
    mapping = load_mapping(MAPPING)
    mapping.require_any = []
    headers, rows = read_csv(SAMPLE)
    _, report = process(headers, rows, mapping)
    assert [d["reason"] for d in report.dropped] == ["empty_row"]
