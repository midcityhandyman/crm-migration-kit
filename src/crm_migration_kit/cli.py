"""Command line entry point: crm-migrate run | check-mapping."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .mapping import MappingError, load_mapping
from .pipeline import CLEANED_NAME, REPORT_JSON_NAME, REPORT_MD_NAME, Settings, read_csv, run_migration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crm-migrate",
        description="Clean, dedupe and map a contacts CSV for a CRM migration.",
    )
    parser.add_argument("--version", action="version", version=f"crm-migrate {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the migration and write the cleaned file and report")
    run.add_argument("--input", required=True, help="source contacts CSV")
    run.add_argument("--mapping", required=True, help="YAML mapping file")
    run.add_argument("--out-dir", default="out", help="folder for the outputs (default: out)")
    run.add_argument("--country-code", help="default country code for 10 digit phones (default: 1)")
    run.add_argument("--name-similarity", type=float, help="0 to 1, how alike names must be to merge on phone")
    run.add_argument("--fail-on-flags", action="store_true", help="exit with code 2 when any row is flagged")
    run.add_argument("--quiet", action="store_true", help="print only the summary line")

    check = sub.add_parser("check-mapping", help="validate a mapping file, optionally against a CSV header")
    check.add_argument("--mapping", required=True)
    check.add_argument("--input", help="CSV whose header should be checked against the mapping")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if args.country_code:
        settings = replace(settings, default_country_code=args.country_code.lstrip("+"))
    if args.name_similarity is not None:
        settings = replace(settings, name_similarity=args.name_similarity)

    report = run_migration(args.input, args.mapping, args.out_dir, settings)
    s = report.summary()
    if not args.quiet:
        print(report.to_markdown())
    out = Path(args.out_dir)
    print(
        f"Read {s['rows_read']}, dropped {s['rows_dropped']}, merged {s['rows_merged_away']}, "
        f"wrote {s['rows_written']}, flagged {s['rows_flagged']} for review."
    )
    print(f"Outputs: {(out / CLEANED_NAME).as_posix()}, {(out / REPORT_JSON_NAME).as_posix()}, "
          f"{(out / REPORT_MD_NAME).as_posix()}")
    return 2 if args.fail_on_flags and report.flags else 0


def _cmd_check(args: argparse.Namespace) -> int:
    mapping = load_mapping(args.mapping)
    print(f"Mapping OK: {len(mapping.source_columns)} source fields, {len(mapping.fields)} target fields.")
    if args.input:
        headers, _ = read_csv(args.input)
        resolved, unmapped = mapping.resolve_headers(headers)
        for header, canonical in resolved.items():
            print(f"  {header.strip()!r} -> {canonical}")
        missing = sorted(set(mapping.source_columns) - set(resolved.values()))
        if unmapped:
            print("Ignored columns: " + ", ".join(unmapped))
        if missing:
            print("Source fields with no matching column: " + ", ".join(missing))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _cmd_run(args) if args.command == "run" else _cmd_check(args)
    except MappingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
