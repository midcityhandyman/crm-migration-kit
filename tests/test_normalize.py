import pytest

from crm_migration_kit.normalize import (
    clean_name,
    email_match_key,
    name_similarity,
    normalize_email,
    normalize_phone,
    split_full_name,
)


@pytest.mark.parametrize(
    "raw",
    ["(555) 555-0101", "555.555.0101", "+1 555 555 0101", "1-555-555-0101", "5555550101", " 555 555 0101 "],
)
def test_phone_formats_normalise_to_one_value(raw):
    assert normalize_phone(raw).value == "+15555550101"


@pytest.mark.parametrize("raw,ext", [("555-555-0102 x204", "204"), ("555-555-0110 ext. 7", "7"), ("5555550102 #33", "33")])
def test_phone_extension_is_split_off(raw, ext):
    result = normalize_phone(raw)
    assert result.value.startswith("+1555555")
    assert result.extension == ext
    assert result.issue is None


@pytest.mark.parametrize("raw", ["555-01", "call the office", "123456789012345678"])
def test_bad_phone_is_blanked_and_flagged(raw):
    result = normalize_phone(raw)
    assert result.value == ""
    assert result.issue == "invalid_phone"


def test_blank_phone_is_not_an_issue():
    assert normalize_phone("  ") == normalize_phone(None)
    assert normalize_phone("").issue is None


def test_phone_country_code_is_configurable_and_plus_is_kept():
    assert normalize_phone("5555550101", default_country_code="44").value == "+445555550101"
    assert normalize_phone("+61 5550 0101 0").value == "+61555001010"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Alex.Sample@Example.com ", "alex.sample@example.com"),
        ("mailto:pat.sampleton@example.net", "pat.sampleton@example.net"),
        ("Robin Faux <robin.faux@example.com>", "robin.faux@example.com"),
        ("quinn.dummy@example.com.", "quinn.dummy@example.com"),
    ],
)
def test_email_cleanup(raw, expected):
    assert normalize_email(raw).value == expected
    assert normalize_email(raw).issue is None


def test_email_comma_in_domain_is_repaired_and_reported():
    result = normalize_email("drew.testman@example,com")
    assert result.value == "drew.testman@example.com"
    assert result.issue == "email_repaired"


@pytest.mark.parametrize("raw", ["casey@example", "not an email", "a@@example.com", "@example.com"])
def test_invalid_email(raw):
    result = normalize_email(raw)
    assert result.value == ""
    assert result.issue == "invalid_email"


def test_email_match_key_plus_tags():
    assert email_match_key("sam.demoson+crm@example.com") == "sam.demoson@example.com"
    assert email_match_key("sam.demoson+crm@example.com", ignore_plus_tags=False) == "sam.demoson+crm@example.com"
    assert email_match_key("") == ""


def test_names():
    assert clean_name("  ALEX   SAMPLE ") == "Alex Sample"
    assert clean_name("o'sample-test") == "O'Sample-Test"
    assert clean_name("McSample") == "McSample"  # mixed case is left alone
    assert split_full_name("TRIALRUN, HARPER") == ("Harper", "Trialrun")
    assert split_full_name("Pat Q. Sampleton") == ("Pat Q.", "Sampleton")
    assert split_full_name("Solo") == ("Solo", "")
    assert split_full_name("") == ("", "")


def test_name_similarity():
    assert name_similarity("Alex", "Sample", "ALEX", "SAMPLE") == 1.0
    assert name_similarity("J.", "Testerson", "Jordan", "Testerson") == 0.9
    assert name_similarity("Taylor", "Mockwell", "Jamie", "Mockwell") < 0.82
    assert name_similarity("", "", "Alex", "Sample") is None
