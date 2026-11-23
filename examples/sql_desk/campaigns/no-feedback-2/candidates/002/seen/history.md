# Candidates so far

The harness in `harness/` is candidate 000.

## Candidate 001, a change to 000
The SQL prompt now includes a bounded sample of stored values from likely categorical columns and lookup tables, prioritizing fields whose names overlap with the question. This should reduce incorrect filters caused by guessed status labels, region codes, or category spellings. The harness still makes one model call and falls back to the schema-only prompt if the read-only probes fail.

Changed: desk.py (+74 -3)

