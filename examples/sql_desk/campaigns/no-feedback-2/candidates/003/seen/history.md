# Candidates so far

The harness in `harness/` is candidate 000.

## Candidate 001, a change to 000
The SQL prompt now includes a bounded sample of stored values from likely categorical columns and lookup tables, prioritizing fields whose names overlap with the question. This should reduce incorrect filters caused by guessed status labels, region codes, or category spellings. The harness still makes one model call and falls back to the schema-only prompt if the read-only probes fail.

Changed: desk.py (+74 -3)

## Candidate 002, a change to 000
The harness now checks each generated SELECT with a read-only `LIMIT 0` probe and makes one repair attempt only if the check fails. Giving the model SQLite’s error should help it fix malformed SQL, unknown tables or columns, and unsupported functions without adding a second model call for queries that pass. The probe checks whether SQLite can compile the query, not whether it answers the question correctly.

Changed: desk.py (+56 -4)

