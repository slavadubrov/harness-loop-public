# Candidates so far

The harness in `harness/` is candidate 000.

## Candidate 001, a change to 000: screened
The harness now uses bounded, read-only queries to discover the exact labels stored in low-cardinality text columns and includes them in the existing model prompt. This targets the observed failures where otherwise valid SQL used guessed order statuses, country names, or product categories instead of the database’s stored codes. It still makes one model call per question and falls back to the schema alone if it cannot discover any labels.

Changed: desk.py (+75 -3)
Decision: development success 0.00 is not above the base's 0.68; validation was not run

