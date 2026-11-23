# Campaign on sql-desk

- Saved use case: `sql-desk` v3. Regraded with `sql-desk` v3.
- Model held fixed: `gpt-6.2-sol`
- Runs per task: 3 on development, 3 on validation, 3 on test
- Adoption rule: one step of a loop, intervals at 95.00%
- The campaign proposed 2 candidates and adopted 1. Regrading supports 1 on the recorded path.
- Improver: $0.16 known cost in 1.9 minutes.
- Evaluation: 432 runs of candidates in 2.4 minutes, 108 more for the noise check and 216 on the test tasks
- All evaluation phases: 756 runs, $0.9990 in reported costs.
- Recorded stop: no development task fails
- Noise check, the starting harness against itself on new samples: success +0.00 (+0.00 to +0.00), inconclusive: as it should be
- With intervals at 97.50%, sensitivity check across 2 candidates: the same decisions

## Every candidate

Development screens and validation decisions are recomputed from saved runs. A decision without grading evidence is marked as recorded only. Test scores describe the harnesses the campaign actually tested.

| Candidate | Change to | Development success | Validation success | Difference on validation | Decision | Why |
|---|---|---|---|---|---|---|
| 000 |  | 0.68 | 0.77 (0.62–0.89) |  | start | the starting harness |
| 001 | 000 | 0.00 | not run |  | screened on dev | development success did not exceed the parent's |
| 002 | 000 | 1.00 | 0.98 (0.94–1.00) | +0.21 (+0.09 to +0.35) | adopted | success is higher: +0.093 to +0.352 |

## What each candidate changed

**001** (screened on dev). The harness now uses bounded, read-only queries to discover the exact labels stored in low-cardinality text columns and includes them in the existing model prompt. This targets the observed failures where otherwise valid SQL used guessed order statuses, country names, or product categories instead of the database’s stored codes. It still makes one model call per question and falls back to the schema alone if it cannot discover any labels.
Files: `desk.py` (+75 −3). Diff: `candidates/001/patch.diff`.

**002** (adopted). Added a post-draft check for text literals in SQL comparisons. The harness uses bounded, read-only lookups to check the specific columns used by the draft and asks the model to map missing literals to exact stored values only when there is a clear match. It substitutes only those validated literals, leaving the rest of the SQL unchanged. This targets the status, country, and category mismatches in the development feedback, including wrong counts from negated status filters.
Files: `desk.py` (+96 −2). Diff: `candidates/002/patch.diff`.

## Test tasks, scored once

| Harness | Success | pass^k | Violations | $ per task | $ per success | p50 latency, s | p95 latency, s | Calls per task | Tokens per task | Infra errors | Undecided | valid sql |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 000 | 0.58 (0.42–0.75) | 0.58 (k=3) | 0 | $0.00130 (0.00117–0.00145) | $0.00223 (0.00166–0.00325) | 1.64 (1.50–1.75) | 3.04 (2.15–3.46) | 1.00 (1.00–1.00) | 414 (399–432) | 0 | 0 | 1.00 (1.00–1.00) |
| 002 | 0.90 (0.81–0.98) | 0.86 (k=3) | 0 | $0.00151 (0.00131–0.00174) | $0.00169 (0.00142–0.00199) | 1.65 (1.50–2.19) | 3.94 (2.99–4.45) | 1.34 (1.19–1.50) | 506 (454–563) | 0 | 0 | 1.00 (1.00–1.00) |

| Tasks tagged | 000 | 002 |
|---|---|---|
| easy | 0.83 (12 tasks) | 0.92 (12 tasks) |
| hard | 0.42 (12 tasks) | 0.86 (12 tasks) |
| medium | 0.50 (12 tasks) | 0.92 (12 tasks) |

**002** against **000** on 36 tasks: success +0.315 (+0.167 to +0.463).
Better on 13 tasks, worse on 0 tasks.
Candidate minus base: cost_per_task +0.00021 (+0.00012 to +0.00032); latency_p50 +0.01 (-0.10 to +0.37); latency_p95 +0.90 (+0.77 to +1.42); calls_per_task +0.34 (+0.19 to +0.49); tokens_per_task +92 (+52 to +137); valid sql +0.00 (+0.00 to +0.00).
Decision: **adopt**. success is higher: +0.167 to +0.463
