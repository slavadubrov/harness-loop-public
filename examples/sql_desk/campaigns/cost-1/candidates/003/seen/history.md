# Candidates so far

The harness in `harness/` is candidate 002.

## Candidate 001, a change to 000: adopt
I shortened the SQL-generation prompt and asked the model to omit cosmetic output aliases. This should reduce input and output token costs without removing schema details or stored values used to resolve categorical filters. All development tasks already passed, so this change targets cost rather than a known correctness failure.

Changed: desk.py (+4 -7)
Decision: cost_per_task is lower: -0.00012 to -0.00009; success holds: +0.000 to +0.000, no lower than -0.02

## Candidate 002, a change to 001: adopt
I compacted the schema sent to the model by collapsing formatting whitespace and removing repeated `CREATE TABLE` prefixes, while preserving identifiers, types, constraints, and quoted values. The stored-value lookup still uses the original schema. All development tasks already passed, so this change targets lower input-token cost rather than a known correctness failure.

Changed: desk.py (+19 -1)
Decision: cost_per_task is lower: -0.00018 to -0.00016; success holds: +0.000 to +0.000, no lower than -0.02

