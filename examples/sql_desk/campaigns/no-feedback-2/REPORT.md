# Campaign on sql-desk

- Saved use case: `sql-desk` v3. Regraded with `sql-desk` v3.
- Model held fixed: `gpt-6.2-sol`
- Runs per task: 3 on development, 3 on validation, 3 on test
- Adoption rule: one step of a loop, intervals at 95.00%
- The campaign proposed 3 candidates and adopted 0. Regrading supports 0 on the recorded path.
- Improver: $0.10 known cost in 1.8 minutes.
- Evaluation: 612 runs of candidates in 3.1 minutes, 108 more for the noise check and 108 on the test tasks
- All evaluation phases: 828 runs, $1.0822 in reported costs.
- Recorded stop: 3 candidates in a row were not adopted
- Noise check, the starting harness against itself on new samples: success +0.01 (+0.00 to +0.03), inconclusive: as it should be
- With intervals at 98.33%, sensitivity check across 3 candidates: the same decisions

## Every candidate

Development screens and validation decisions are recomputed from saved runs. A decision without grading evidence is marked as recorded only. Test scores describe the harnesses the campaign actually tested.

| Candidate | Change to | Development success | Validation success | Difference on validation | Decision | Why |
|---|---|---|---|---|---|---|
| 000 |  | 0.67 | 0.77 (0.62–0.89) |  | start | the starting harness |
| 001 | 000 | 0.00 | not run |  | screened on dev | development success did not exceed the parent's |
| 002 | 000 | 0.68 | 0.77 (0.62–0.89) | +0.00 (+0.00 to +0.00) | inconclusive | success difference +0.000 to +0.000 does not establish a benefit; keep the base |
| 003 | 000 | 0.68 | 0.75 (0.58–0.89) | -0.02 (-0.06 to +0.00) | rejected (ledger: inconclusive) | 1 of 36 tasks pass less often than with the base by more than 0.5; keep the base |

## What each candidate changed

**001** (screened on dev). The SQL prompt now includes a bounded sample of stored values from likely categorical columns and lookup tables, prioritizing fields whose names overlap with the question. This should reduce incorrect filters caused by guessed status labels, region codes, or category spellings. The harness still makes one model call and falls back to the schema-only prompt if the read-only probes fail.
Files: `desk.py` (+74 −3). Diff: `candidates/001/patch.diff`.

**002** (inconclusive). The harness now checks each generated SELECT with a read-only `LIMIT 0` probe and makes one repair attempt only if the check fails. Giving the model SQLite’s error should help it fix malformed SQL, unknown tables or columns, and unsupported functions without adding a second model call for queries that pass. The probe checks whether SQLite can compile the query, not whether it answers the question correctly.
Files: `desk.py` (+56 −4). Diff: `candidates/002/patch.diff`.

**003** (rejected). I added a short checklist to the SQL prompt that asks the model to identify what each result row represents, return only the requested columns, check for double-counting across joins, preserve entities with no activity when requested, and apply ordering in the final query. This targets queries that run successfully but return the wrong rows, columns, or totals, without adding model calls or database probes.
Files: `desk.py` (+11 −1). Diff: `candidates/003/patch.diff`.

## Test tasks, scored once

| Harness | Success | pass^k | Violations | $ per task | $ per success | p50 latency, s | p95 latency, s | Calls per task | Tokens per task | Infra errors | Undecided | valid sql |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 000 | 0.58 (0.42–0.75) | 0.58 (k=3) | 0 | $0.00130 (0.00118–0.00145) | $0.00223 (0.00166–0.00324) | 1.60 (1.49–1.74) | 3.04 (2.07–3.26) | 1.00 (1.00–1.00) | 414 (399–431) | 0 | 0 | 1.00 (1.00–1.00) |

| Tasks tagged | 000 |
|---|---|
| easy | 0.83 (12 tasks) |
| hard | 0.42 (12 tasks) |
| medium | 0.50 (12 tasks) |
