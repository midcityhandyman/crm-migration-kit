from pathlib import Path

from crm_migration_kit.cli import main

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = str(ROOT / "sample_data" / "contacts_messy.csv")
MAPPING = str(ROOT / "sample_data" / "mapping.yaml")


def test_run_writes_outputs_and_prints_summary(tmp_path, capsys):
    code = main(["run", "--input", SAMPLE, "--mapping", MAPPING, "--out-dir", str(tmp_path), "--quiet"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Read 29, dropped 3, merged 7, wrote 19, flagged 9 for review." in out
    assert "# Validation report" not in out
    for name in ("cleaned_contacts.csv", "validation_report.json", "validation_report.md"):
        assert (tmp_path / name).is_file()


def test_fail_on_flags_returns_2(tmp_path):
    assert main(["run", "--input", SAMPLE, "--mapping", MAPPING, "--out-dir", str(tmp_path), "--quiet",
                 "--fail-on-flags"]) == 2


def test_name_similarity_flag_changes_merging(tmp_path, capsys):
    main(["run", "--input", SAMPLE, "--mapping", MAPPING, "--out-dir", str(tmp_path), "--quiet",
          "--name-similarity", "0.6"])
    assert "merged 8" in capsys.readouterr().out  # the two rows sharing an office line now merge


def test_check_mapping(capsys):
    assert main(["check-mapping", "--mapping", MAPPING, "--input", SAMPLE]) == 0
    out = capsys.readouterr().out
    assert "Mapping OK" in out and "Ignored columns: Legacy ID" in out


def test_errors_are_reported_without_a_traceback(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("source_columns: {email: []}\ntarget: {fields: [{name: X, from: nope}]}\n", encoding="utf-8")
    assert main(["check-mapping", "--mapping", str(bad)]) == 1
    assert "unknown source field 'nope'" in capsys.readouterr().err
    assert main(["run", "--input", str(tmp_path / "missing.csv"), "--mapping", MAPPING, "--out-dir", str(tmp_path)]) == 1
    assert "file not found" in capsys.readouterr().err
