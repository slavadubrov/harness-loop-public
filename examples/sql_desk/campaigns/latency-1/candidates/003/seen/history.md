# Candidates so far

The harness in `harness/` is candidate 000.

## Candidate 001, a change to 000: inconclusive
I updated the SQL-generation prompt to request short aliases and omit unrequested display labels, comments, and Markdown. The development baseline had no correctness failures, so this change targets tail latency by reducing the number of tokens generated for longer queries, without changing the schema context, model settings, or requested results. The latency improvement has not been measured.

Changed: desk.py (+2 -1)
Decision: latency_p95 changes by -0.37 to +0.34, which does not establish a decrease; keep the base; success holds: +0.000 to +0.000, no lower than -0.02

## Candidate 002, a change to 000: inconclusive
I updated the SQL-generation prompt to favor a direct SELECT when it returns the same rows, while keeping CTEs and subqueries where separate aggregation levels, window filters, or other logic require them. All development runs already passed, so this change targets tail latency from generating unnecessary query layers rather than a known correctness failure. The latency effect has not been measured.

Changed: desk.py (+3 -0)
Decision: latency_p95 changes by -0.71 to +0.81, which does not establish a decrease; keep the base; success holds: +0.000 to +0.000, no lower than -0.02

