# Campaign on sql-desk

- Saved use case: `sql-desk` v3. Regraded with `sql-desk` v3.
- Model held fixed: `gpt-6.2-sol`
- Runs per task: 3 on development, 3 on validation, 3 on test
- Adoption rule: one step of a loop, intervals at 95.00%
- The campaign proposed 3 candidates and adopted 0. Regrading supports 0 on the recorded path.
- Improver: $0.10 known cost in 1.9 minutes.
- Evaluation: 396 runs of candidates in 2.1 minutes, 108 more for the noise check and 108 on the test tasks
- All evaluation phases: 612 runs, $0.8107 in reported costs.
- Recorded stop: 3 candidates in a row were not adopted
- Noise check, the starting harness against itself on new samples: success +0.01 (+0.00 to +0.03), inconclusive: as it should be
- With intervals at 98.33%, sensitivity check across 3 candidates: the same decisions

## Every candidate

Development screens and validation decisions are recomputed from saved runs. A decision without grading evidence is marked as recorded only. Test scores describe the harnesses the campaign actually tested.

| Candidate | Change to | Development success | Validation success | Difference on validation | Decision | Why |
|---|---|---|---|---|---|---|
| 000 |  | 0.67 | 0.77 (0.62–0.89) |  | start | the starting harness |
| 001 | 000 | 0.00 | not run |  | screened on dev | development success did not exceed the parent's |
| 002 | 000 | 0.67 | not run |  | screened on dev | development success did not exceed the parent's |
| 003 | 000 | 0.67 | not run |  | screened on dev | development success did not exceed the parent's |

## What each candidate changed

**001** (screened on dev). The SQL prompt now includes a bounded sample of short, low-cardinality text values alongside the schema. This should reduce syntactically valid queries that return wrong or empty results because the model guessed how a status, category, or other label was stored. The harness uses at most two read-only inspection queries, makes no extra model calls, and falls back to a schema-only prompt if inspection fails.
Files: `desk.py` (+55 −3). Diff: `candidates/001/patch.diff`.

**002** (screened on dev). I updated the SQL prompt to make the model identify what each result row represents and check that joins, aggregates, and ranking preserve that level of detail. This targets queries that run successfully but return inflated totals, omit entities with no matches, rank the wrong rows, or include unrequested columns. The harness still makes one model call and no database inspection queries.
Files: `desk.py` (+13 −0). Diff: `candidates/002/patch.diff`.

**003** (screened on dev). I added a short SQLite value-semantics checklist to the SQL prompt. It targets queries that run but return wrong rows because a timestamp filter drops part of the last day, integer division truncates a ratio, or a NULL in a NOT IN subquery suppresses unmatched rows. The harness still makes one model call and no database inspection queries.
Files: `desk.py` (+12 −1). Diff: `candidates/003/patch.diff`.

## Test tasks, scored once

| Harness | Success | pass^k | Violations | $ per task | $ per success | p50 latency, s | p95 latency, s | Calls per task | Tokens per task | Infra errors | Undecided | valid sql |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 000 | 0.58 (0.42–0.75) | 0.58 (k=3) | 0 | $0.00130 (0.00118–0.00145) | $0.00223 (0.00166–0.00323) | 1.62 (1.48–1.74) | 2.93 (2.03–2.99) | 1.00 (1.00–1.00) | 414 (399–431) | 0 | 0 | 1.00 (1.00–1.00) |

| Tasks tagged | 000 |
|---|---|
| easy | 0.83 (12 tasks) |
| hard | 0.42 (12 tasks) |
| medium | 0.50 (12 tasks) |
