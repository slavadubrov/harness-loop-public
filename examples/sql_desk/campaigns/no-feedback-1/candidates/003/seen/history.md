# Candidates so far

The harness in `harness/` is candidate 000.

## Candidate 001, a change to 000
The SQL prompt now includes a bounded sample of short, low-cardinality text values alongside the schema. This should reduce syntactically valid queries that return wrong or empty results because the model guessed how a status, category, or other label was stored. The harness uses at most two read-only inspection queries, makes no extra model calls, and falls back to a schema-only prompt if inspection fails.

Changed: desk.py (+55 -3)

## Candidate 002, a change to 000
I updated the SQL prompt to make the model identify what each result row represents and check that joins, aggregates, and ranking preserve that level of detail. This targets queries that run successfully but return inflated totals, omit entities with no matches, rank the wrong rows, or include unrequested columns. The harness still makes one model call and no database inspection queries.

Changed: desk.py (+13 -0)

