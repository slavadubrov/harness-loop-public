# Candidates so far

The harness in `harness/` is candidate 000.

## Candidate 001, a change to 000: inconclusive
I updated the SQL-generation prompt to request short aliases and omit unrequested display labels, comments, and Markdown. The development baseline had no correctness failures, so this change targets tail latency by reducing the number of tokens generated for longer queries, without changing the schema context, model settings, or requested results. The latency improvement has not been measured.

Changed: desk.py (+2 -1)
Decision: latency_p95 changes by -0.37 to +0.34, which does not establish a decrease; keep the base; success holds: +0.000 to +0.000, no lower than -0.02

