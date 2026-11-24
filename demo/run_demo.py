"""Offline demo: run the kit on the synthetic sample and print the report.

Usage: python demo/run_demo.py
Writes demo/out/cleaned_contacts.csv and the two report files, and saves
everything it prints to demo/output.txt.
"""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crm_migration_kit.cli import main  # noqa: E402


def run() -> str:
    os.chdir(ROOT)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        print("$ crm-migrate check-mapping --mapping sample_data/mapping.yaml --input sample_data/contacts_messy.csv")
        main(["check-mapping", "--mapping", "sample_data/mapping.yaml", "--input", "sample_data/contacts_messy.csv"])
        print()
        print("$ crm-migrate run --input sample_data/contacts_messy.csv --mapping sample_data/mapping.yaml --out-dir demo/out")
        main(["run", "--input", "sample_data/contacts_messy.csv", "--mapping", "sample_data/mapping.yaml",
              "--out-dir", "demo/out"])
        print()
        print("$ head -6 demo/out/cleaned_contacts.csv")
        lines = (ROOT / "demo" / "out" / "cleaned_contacts.csv").read_text(encoding="utf-8").splitlines()
        print("\n".join(lines[:6]))
    return buffer.getvalue()


if __name__ == "__main__":
    text = run()
    with open(ROOT / "demo" / "output.txt", "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    sys.stdout.write(text)
