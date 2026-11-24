from crm_migration_kit.dedupe import dedupe, merge_records


def rec(row, first="", last="", email="", phone="", company="", **extra):
    return {"_row": row, "first_name": first, "last_name": last, "email": email,
            "phone": phone, "company": company, **extra}


def test_same_email_merges_and_explains():
    result = dedupe([
        rec(2, "Alex", "Sample", "alex.sample@example.com", "+15555550101"),
        rec(3, "Alex", "Sample", "alex.sample@example.com"),
    ])
    assert len(result.records) == 1
    assert result.records[0]["_rows"] == [2, 3]
    group = result.merges[0]
    assert (group.kept_row, group.merged_rows) == (2, [3])
    assert group.links[0].rule == "email_exact"
    assert "alex.sample@example.com" in group.links[0].reason


def test_plus_tag_emails_match_only_when_enabled():
    records = [rec(2, "Sam", "Demoson", "sam.demoson+crm@example.com"), rec(3, "Sam", "Demoson", "sam.demoson@example.com")]
    assert len(dedupe(records).records) == 1
    assert len(dedupe(records, ignore_plus_tags=False).records) == 2


def test_same_phone_similar_name_merges():
    result = dedupe([
        rec(5, "Jordan", "Testerson", "jordan.testerson@example.com", "+15555550102"),
        rec(6, "J.", "Testerson", "", "+15555550102"),
    ])
    assert len(result.records) == 1
    assert result.merges[0].links[0].rule == "phone_and_name"
    assert result.records[0]["first_name"] == "Jordan"
    assert {"field": "first_name", "kept": "Jordan", "discarded": "J.", "from_row": 6} in result.merges[0].conflicts


def test_same_phone_different_names_is_flagged_not_merged():
    result = dedupe([
        rec(11, "Taylor", "Mockwell", "taylor.mockwell@example.com", "+15555550104"),
        rec(12, "Jamie", "Mockwell", "jamie.mockwell@example.com", "+15555550104"),
    ])
    assert len(result.records) == 2
    assert result.merges == []
    assert [(f["row"], f["code"]) for f in result.flags] == [(11, "shared_phone"), (12, "shared_phone")]


def test_same_phone_missing_name_merges():
    result = dedupe([rec(2, "Alex", "Sample", "", "+15555550101"), rec(3, "", "", "", "+15555550101")])
    assert len(result.records) == 1
    assert result.merges[0].links[0].rule == "phone_name_missing"


def test_name_and_company_alone_only_flags():
    result = dedupe([
        rec(17, "Robin", "Faux", "robin.faux@example.com", "+15555550107", "Faux Interiors"),
        rec(18, "Robin", "Faux", "", "+15555550199", "Faux Interiors"),
    ])
    assert len(result.records) == 2
    assert {f["code"] for f in result.flags} == {"possible_duplicate"}


def test_merges_are_transitive_and_not_double_flagged():
    result = dedupe([
        rec(2, "Alex", "Sample", "alex.sample@example.com", "", "Example Property Group"),
        rec(3, "Alex", "Sample", "alex.sample@example.com", "+15555550101", "Example Property Group"),
        rec(4, "Alex", "Sample", "", "+15555550101"),
    ])
    assert len(result.records) == 1
    assert result.records[0]["_rows"] == [2, 3, 4]
    assert {link.rule for link in result.merges[0].links} == {"email_exact", "phone_and_name"}
    assert result.flags == []  # rows 2 and 3 share name and company but were merged anyway


def test_survivor_is_most_complete_and_blanks_are_filled():
    merged, conflicts = merge_records([
        rec(2, "Reese", "Stubb", "reese.stubb@example.com", "", city=""),
        rec(3, "Reese", "Stubb", "reese.stubb@example.org", "+15555550111", city="Faketown"),
    ])
    assert merged["_row"] == 3
    assert merged["email"] == "reese.stubb@example.org"
    assert conflicts == [{"field": "email", "kept": "reese.stubb@example.org",
                          "discarded": "reese.stubb@example.com", "from_row": 2}]

    merged, conflicts = merge_records([rec(2, "Alex", "Sample", "a@example.com"), rec(3, "alex", "sample", "", "+15555550101")])
    assert merged["_row"] == 2 and merged["phone"] == "+15555550101"
    assert conflicts == []  # case only differences are not conflicts


def test_unique_records_pass_through_in_order():
    result = dedupe([rec(4, "B", "Two", "b@example.com"), rec(2, "A", "One", "a@example.com")])
    assert [r["_row"] for r in result.records] == [2, 4]
    assert result.merges == [] and result.flags == []


def test_nameless_record_does_not_join_two_different_people():
    # Rows 11 and 12 share an office line under different names. Row 13 has the
    # same phone and no name: it must not pull the two people into one record.
    result = dedupe([
        rec(11, "Taylor", "Mockwell", "taylor.mockwell@example.com", "+15555550104"),
        rec(12, "Jamie", "Mockwell", "jamie.mockwell@example.com", "+15555550104"),
        rec(13, "", "", "", "+15555550104"),
    ])
    assert [r["_rows"] for r in result.records] == [[11], [12], [13]]
    assert result.merges == []
    assert {f["row"] for f in result.flags} == {11, 12, 13}
    assert {f["code"] for f in result.flags} == {"shared_phone"}


def test_nameless_record_merges_when_phone_has_one_person():
    result = dedupe([
        rec(5, "Jordan", "Testerson", "", "+15555550102"),
        rec(6, "J.", "Testerson", "", "+15555550102"),
        rec(7, "", "", "", "+15555550102"),
        rec(8, "", "", "", "+15555550102"),
    ])
    assert [r["_rows"] for r in result.records] == [[5, 6, 7, 8]]
    assert [link.rule for link in result.merges[0].links] == [
        "phone_and_name", "phone_name_missing", "phone_name_missing"]
    assert result.flags == []


def test_two_nameless_records_on_one_phone_merge_with_accurate_reason():
    result = dedupe([rec(2, phone="+15555550120"), rec(3, phone="+15555550120")])
    assert len(result.records) == 1
    assert result.merges[0].links[0].reason == "same phone +15555550120 and neither record has a name"
