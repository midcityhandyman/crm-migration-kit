"""YAML mapping: source headers -> canonical fields -> target schema."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Canonical fields the normaliser and the dedupe rules know about.
CORE_FIELDS = ("full_name", "first_name", "last_name", "email", "phone", "company")
# Fields the pipeline derives during normalisation.
DERIVED_FIELDS = ("phone_ext",)
DEFAULT_BLANK_TOKENS = ("n/a", "na", "none", "null", "unknown", "-", "--", "tbd")


class MappingError(ValueError):
    """Raised when the mapping file is missing something or contradicts itself."""


def header_key(header: str) -> str:
    """Compare headers loosely: " E-mail Address " equals "email address"."""
    return re.sub(r"[^a-z0-9]", "", (header or "").lower())


@dataclass
class TargetField:
    name: str
    source: str | None = None  # "from" in YAML
    template: str | None = None
    constant: str | None = None
    default: str = ""
    value_map: dict[str, str] = field(default_factory=dict)
    unmapped: str | None = None  # value used when value_map has no entry
    required: bool = False

    def references(self) -> list[str]:
        if self.source:
            return [self.source]
        if self.template:
            return [name for _, name, _, _ in string.Formatter().parse(self.template) if name]
        return []

    def apply(self, record: dict) -> tuple[str, list[tuple[str, str]]]:
        """Return the target value and any (code, detail) issues."""
        issues: list[tuple[str, str]] = []
        if self.constant is not None:
            value = self.constant
        elif self.template is not None:
            values = {name: record.get(name, "") for name in self.references()}
            value = re.sub(r"\s+", " ", self.template.format(**values)).strip(" ,")
        else:
            value = record.get(self.source or "", "")

        if value and self.value_map:
            mapped = self.value_map.get(value.strip().lower())
            if mapped is not None:
                value = mapped
            else:
                fallback = self.unmapped if self.unmapped is not None else value
                issues.append(("unmapped_value", f"{self.name}: '{value}' is not in value_map, wrote '{fallback}'"))
                value = fallback
        if not value:
            value = self.default
        if not value and self.required:
            issues.append(("missing_required", f"{self.name} is required but empty"))
        return value, issues


@dataclass
class Mapping:
    source_columns: dict[str, list[str]]
    fields: list[TargetField]
    require_any: list[str] = field(default_factory=lambda: ["email", "phone"])
    blank_tokens: list[str] = field(default_factory=lambda: list(DEFAULT_BLANK_TOKENS))
    ignore_email_plus_tags: bool = True
    audit_column: str | None = None

    def resolve_headers(self, headers: list[str]) -> tuple[dict[str, str], list[str]]:
        """Map each CSV header to a canonical field. Returns (resolved, unmapped)."""
        lookup: dict[str, str] = {}
        for canonical, aliases in self.source_columns.items():
            for alias in [canonical, *aliases]:
                lookup[header_key(alias)] = canonical
        resolved: dict[str, str] = {}
        unmapped: list[str] = []
        for header in headers:
            canonical = lookup.get(header_key(header))
            if canonical:
                resolved[header] = canonical
            elif header and header.strip():
                unmapped.append(header.strip())
        return resolved, unmapped

    def target_headers(self) -> list[str]:
        names = [f.name for f in self.fields]
        if self.audit_column:
            names.append(self.audit_column)
        return names


def parse_mapping(data: dict) -> Mapping:
    """Build a Mapping from parsed YAML and report every problem at once."""
    errors: list[str] = []
    if not isinstance(data, dict):
        raise MappingError("mapping file must be a YAML object")

    source_columns: dict[str, list[str]] = {}
    raw_sources = data.get("source_columns") or {}
    if not isinstance(raw_sources, dict) or not raw_sources:
        errors.append("source_columns: must list at least one canonical field")
        raw_sources = {}
    for canonical, aliases in raw_sources.items():
        if aliases is None:
            aliases = []
        if isinstance(aliases, str):
            aliases = [aliases]
        source_columns[str(canonical)] = [str(a) for a in aliases]

    known = set(source_columns) | set(DERIVED_FIELDS)
    if "full_name" in source_columns:
        known |= {"first_name", "last_name"}  # derived by splitting the full name

    rules = data.get("rules") or {}
    # Default: whichever of email and phone the source actually has.
    default_required = [name for name in ("email", "phone") if name in source_columns]
    require_any = [str(x) for x in rules.get("require_any", default_required) or []]
    for name in require_any:
        if name not in known:
            errors.append(f"rules.require_any: '{name}' is not a source field")

    target = data.get("target") or {}
    fields: list[TargetField] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(target.get("fields") or []):
        label = f"target.fields[{index}]"
        if not isinstance(raw, dict) or not raw.get("name"):
            errors.append(f"{label}: needs a name")
            continue
        name = str(raw["name"])
        label = f"target field '{name}'"
        if name in seen_names:
            errors.append(f"{label}: defined twice")
        seen_names.add(name)
        kinds = [k for k in ("from", "template", "constant") if raw.get(k) is not None]
        if len(kinds) != 1:
            errors.append(f"{label}: needs exactly one of from, template, constant")
            continue
        tf = TargetField(
            name=name,
            source=raw.get("from"),
            template=raw.get("template"),
            constant=None if raw.get("constant") is None else str(raw["constant"]),
            default=str(raw.get("default", "") or ""),
            value_map={str(k).strip().lower(): str(v) for k, v in (raw.get("value_map") or {}).items()},
            unmapped=None if raw.get("unmapped") is None else str(raw["unmapped"]),
            required=bool(raw.get("required", False)),
        )
        for ref in tf.references():
            if ref not in known:
                errors.append(f"{label}: refers to unknown source field '{ref}'")
        fields.append(tf)
    if not fields and not any("target.fields" in e for e in errors):
        errors.append("target.fields: must list at least one field")

    if errors:
        raise MappingError("invalid mapping:\n  - " + "\n  - ".join(errors))

    return Mapping(
        source_columns=source_columns,
        fields=fields,
        require_any=require_any,
        blank_tokens=[str(t).strip().lower() for t in rules.get("blank_tokens", DEFAULT_BLANK_TOKENS)],
        ignore_email_plus_tags=bool(rules.get("ignore_email_plus_tags", True)),
        audit_column=target.get("audit_column"),
    )


def load_mapping(path: str | Path) -> Mapping:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise MappingError(f"mapping file is not valid YAML: {exc}") from exc
    return parse_mapping(data)
