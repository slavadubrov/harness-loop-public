# Campaign on sql-desk

- Saved use case: `sql-desk` v3. Regraded with `sql-desk` v3.
- Model held fixed: `gpt-6.2-sol`
- Runs per task: 3 on development, 3 on validation, 3 on test
- Adoption rule: one step of a loop, intervals at 95.00%
- The campaign proposed 1 candidates and adopted 1. Regrading supports 1 on the recorded path.
- Improver: $0.08 known cost in 0.9 minutes.
- Evaluation: 360 runs of candidates in 2.0 minutes, 108 more for the noise check and 216 on the test tasks
- All evaluation phases: 684 runs, $1.0179 in reported costs.
- Recorded stop: no development task fails
- Noise check, the starting harness against itself on new samples: success +0.01 (+0.00 to +0.03), inconclusive: as it should be
- With intervals at 95.00%, sensitivity check across 1 candidates: the same decisions

## Every candidate

Development screens and validation decisions are recomputed from saved runs. A decision without grading evidence is marked as recorded only. Test scores describe the harnesses the campaign actually tested.

| Candidate | Change to | Development success | Validation success | Difference on validation | Decision | Why |
|---|---|---|---|---|---|---|
| 000 |  | 0.67 | 0.77 (0.62–0.89) |  | start | the starting harness |
| 001 | 000 | 1.00 | 1.00 (1.00–1.00) | +0.23 (+0.11 to +0.37) | adopted | success is higher: +0.111 to +0.370 |

## What each candidate changed

**001** (adopted). The harness now uses a single read-only probe to find small sets of stored text values and adds them to the SQL prompt. This should fix failures where the model guessed order statuses, country names, or product categories instead of using the database’s actual codes, including in cancellation rates and non-cancelled order counts. The harness still makes one model call and falls back to the schema alone if the probe fails.
Files: `desk.py` (+78 −3). Diff: `candidates/001/patch.diff`.

## Test tasks, scored once

| Harness | Success | pass^k | Violations | $ per task | $ per success | p50 latency, s | p95 latency, s | Calls per task | Tokens per task | Infra errors | Undecided | valid sql |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 000 | 0.58 (0.42–0.75) | 0.58 (k=3) | 0 | $0.00130 (0.00117–0.00144) | $0.00222 (0.00166–0.00325) | 1.60 (1.51–1.76) | 2.87 (2.19–3.17) | 1.00 (1.00–1.00) | 414 (399–431) | 0 | 0 | 1.00 (1.00–1.00) |
| 001 | 1.00 (1.00–1.00) | 1.00 (k=3) | 0 | $0.00187 (0.00171–0.00204) | $0.00187 (0.00171–0.00204) | 1.68 (1.57–1.87) | 3.29 (2.42–3.51) | 1.00 (1.00–1.00) | 650 (632–670) | 0 | 0 | 1.00 (1.00–1.00) |

| Tasks tagged | 000 | 001 |
|---|---|---|
| easy | 0.83 (12 tasks) | 1.00 (12 tasks) |
| hard | 0.42 (12 tasks) | 1.00 (12 tasks) |
| medium | 0.50 (12 tasks) | 1.00 (12 tasks) |

**001** against **000** on 36 tasks: success +0.417 (+0.250 to +0.583).
Better on 15 tasks, worse on 0 tasks.
Candidate minus base: cost_per_task +0.00057 (+0.00052 to +0.00062); latency_p50 +0.08 (-0.01 to +0.19); latency_p95 +0.42 (+0.02 to +0.55); calls_per_task +0.00 (+0.00 to +0.00); tokens_per_task +236 (+232 to +241); valid sql +0.00 (+0.00 to +0.00).
Decision: **adopt**. success is higher: +0.250 to +0.583
