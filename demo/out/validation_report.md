# Validation report

- Input: `sample_data/contacts_messy.csv`
- Mapping: `sample_data/mapping.yaml`

## Summary

| Measure | Count |
| --- | ---: |
| Rows read | 29 |
| Rows dropped | 3 |
| Rows merged into another row | 7 |
| Merge groups | 6 |
| Rows written | 19 |
| Rows flagged for review | 9 |

Check: read = dropped + merged + written is true.

## Dropped rows

- Row 9: no_contact_method. No valid email or phone after normalisation.
- Row 10: empty_row. No mapped column has a value.
- Row 19: no_contact_method. No valid email or phone after normalisation.

## Merged rows

- Kept row 3, merged in row(s) 2, 4
  - email_exact: rows 2 and 3, same email address alex.sample@example.com
  - phone_and_name: rows 2 and 4, same phone +15555550101 and name similarity 1.00 (threshold 0.82)
  - conflict on lead_source: kept 'Web', discarded 'referral' from row 4
  - conflict on notes: kept 'duplicate entry from old system', discarded 'called twice' from row 4
- Kept row 5, merged in row(s) 6
  - phone_and_name: rows 5 and 6, same phone +15555550102 and name similarity 0.90 (threshold 0.82)
  - conflict on first_name: kept 'Jordan', discarded 'J.' from row 6
- Kept row 13, merged in row(s) 14
  - email_exact: rows 13 and 14, same email address sam.demoson@example.com
  - conflict on email: kept 'sam.demoson+crm@example.com', discarded 'sam.demoson@example.com' from row 14
  - conflict on lead_source: kept 'email campaign', discarded 'email' from row 14
- Kept row 20, merged in row(s) 21
  - email_exact: rows 20 and 21, same email address quinn.dummy@example.com
  - conflict on lead_source: kept 'web', discarded 'Website' from row 21
- Kept row 24, merged in row(s) 25
  - email_exact: rows 24 and 25, same email address harper.trialrun@example.com
- Kept row 27, merged in row(s) 26
  - phone_and_name: rows 26 and 27, same phone +15555550111 and name similarity 1.00 (threshold 0.82)
  - conflict on email: kept 'reese.stubb@example.org', discarded 'reese.stubb@example.com' from row 26

## Flagged rows

- Row 7: invalid_email. Could not read email 'casey@example', left blank.
- Row 8: invalid_phone. Could not read phone '555-01', left blank.
- Row 11: shared_phone. same phone +15555550104 but names differ (similarity 0.67), not merged (other row 12)
- Row 12: shared_phone. same phone +15555550104 but names differ (similarity 0.67), not merged (other row 11)
- Row 16: email_repaired. Email 'drew.testman@example,com' repaired to 'drew.testman@example.com', please confirm.
- Row 17: possible_duplicate. same name and company but no shared email or phone, not merged (other row 18)
- Row 18: possible_duplicate. same name and company but no shared email or phone, not merged (other row 17)
- Row 22: unmapped_value. LeadSource: 'yellow pages' is not in value_map, wrote 'Other'
- Row 23: missing_required. LastName is required but empty

## Source columns not in the mapping (ignored)

- Legacy ID
