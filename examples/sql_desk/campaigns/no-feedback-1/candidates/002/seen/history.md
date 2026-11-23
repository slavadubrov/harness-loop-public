# Candidates so far

The harness in `harness/` is candidate 000.

## Candidate 001, a change to 000
The SQL prompt now includes a bounded sample of short, low-cardinality text values alongside the schema. This should reduce syntactically valid queries that return wrong or empty results because the model guessed how a status, category, or other label was stored. The harness uses at most two read-only inspection queries, makes no extra model calls, and falls back to a schema-only prompt if inspection fails.

Changed: desk.py (+55 -3)

