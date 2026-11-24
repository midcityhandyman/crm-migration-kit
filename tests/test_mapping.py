import pytest

from crm_migration_kit.mapping import MappingError, TargetField, header_key, load_mapping, parse_mapping

BASE = {
    "source_columns": {"first_name": ["First"], "last_name": ["Last"], "email": ["E-mail"], "phone": ["Tel"],
                       "lead_source": ["Source"]},
    "target": {"fields": [{"name": "Email", "from": "email"}]},
}


def test_header_matching_ignores_case_spacing_and_punctuation():
    assert header_key(" E-mail Address ") == header_key("email_address")
    mapping = parse_mapping(BASE)
    resolved, unmapped = mapping.resolve_headers([" FIRST ", "e mail", "phone", "Legacy ID", ""])
    assert resolved == {" FIRST ": "first_name", "e mail": "email", "phone": "phone"}
    assert unmapped == ["Legacy ID"]


def test_from_default_and_required():
    field = TargetField(name="LastName", source="last_name", required=True)
    assert field.apply({"last_name": "Sample"}) == ("Sample", [])
    value, issues = field.apply({"last_name": ""})
    assert value == "" and issues[0][0] == "missing_required"
    assert TargetField(name="City", source="city", default="Unknown").apply({}) == ("Unknown", [])


def test_template_and_constant():
    field = TargetField(name="DisplayName", template="{first_name} {last_name}")
    assert field.apply({"first_name": "Alex", "last_name": "Sample"})[0] == "Alex Sample"
    assert field.apply({"first_name": "", "last_name": "Sample"})[0] == "Sample"
    assert TargetField(name="Batch", constant="b1").apply({}) == ("b1", [])


def test_value_map_is_case_insensitive_and_reports_unknown_values():
    field = TargetField(name="LeadSource", source="lead_source", value_map={"web": "Website"}, unmapped="Other")
    assert field.apply({"lead_source": " WEB "}) == ("Website", [])
    value, issues = field.apply({"lead_source": "yellow pages"})
    assert value == "Other" and issues[0][0] == "unmapped_value"
    keep = TargetField(name="LeadSource", source="lead_source", value_map={"web": "Website"})
    assert keep.apply({"lead_source": "yellow pages"})[0] == "yellow pages"


def test_invalid_mapping_reports_every_problem():
    bad = {
        "source_columns": {"email": []},
        "rules": {"require_any": ["email", "fax"]},
        "target": {"fields": [
            {"name": "A", "from": "nope"},
            {"name": "B", "from": "email", "constant": "x"},
            {"name": "A", "template": "{email} {missing}"},
            {"from": "email"},
        ]},
    }
    with pytest.raises(MappingError) as err:
        parse_mapping(bad)
    text = str(err.value)
    for expected in ("'fax' is not a source field", "unknown source field 'nope'", "exactly one of",
                     "defined twice", "unknown source field 'missing'", "needs a name"):
        assert expected in text


def test_empty_or_broken_files(tmp_path):
    with pytest.raises(MappingError):
        parse_mapping({})
    with pytest.raises(MappingError):
        parse_mapping(["not", "a", "mapping"])
    broken = tmp_path / "broken.yaml"
    broken.write_text("target: [unclosed", encoding="utf-8")
    with pytest.raises(MappingError):
        load_mapping(broken)


def test_full_name_makes_first_and_last_available():
    mapping = parse_mapping({
        "source_columns": {"full_name": ["Name"], "email": []},
        "target": {"fields": [{"name": "Last", "from": "last_name"}, {"name": "Ext", "from": "phone_ext"}]},
    })
    assert mapping.target_headers() == ["Last", "Ext"]
