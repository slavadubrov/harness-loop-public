# Candidates so far

The harness in `harness/` is candidate 005.

## Candidate 001, a change to 000: adopt
I shortened the SQL-generation prompt and asked the model to omit cosmetic output aliases. This should reduce input and output token costs without removing schema details or stored values used to resolve categorical filters. All development tasks already passed, so this change targets cost rather than a known correctness failure.

Changed: desk.py (+4 -7)
Decision: cost_per_task is lower: -0.00012 to -0.00009; success holds: +0.000 to +0.000, no lower than -0.02

## Candidate 002, a change to 001: adopt
I compacted the schema sent to the model by collapsing formatting whitespace and removing repeated `CREATE TABLE` prefixes, while preserving identifiers, types, constraints, and quoted values. The stored-value lookup still uses the original schema. All development tasks already passed, so this change targets lower input-token cost rather than a known correctness failure.

Changed: desk.py (+19 -1)
Decision: cost_per_task is lower: -0.00018 to -0.00016; success holds: +0.000 to +0.000, no lower than -0.02

## Candidate 003, a change to 002: adopt
I shortened the stored-text portion of the model prompt by displaying simple categorical values without redundant quotes and retaining quotes where they prevent ambiguity. The same domains pass the same inclusion checks, so the model still sees exact values for filters and CASE expressions. All development tasks already passed, so this change targets input-token cost rather than a known correctness failure.

Changed: desk.py (+18 -2)
Decision: cost_per_task is lower: -0.00009 to -0.00007; success holds: +0.000 to +0.000, no lower than -0.02

## Candidate 004, a change to 003: adopt
I shortened the schema sent to the model by rendering repeated `PRIMARY KEY` and `NOT NULL` constraints as `PK` and `NN`, with a legend defining the abbreviations. Quoted text, stored-value hints, and query behavior are unchanged. All 24 development tasks already passed, so this change targets lower input-token cost rather than a known correctness failure; the savings have not been measured.

Changed: desk.py (+16 -3)
Decision: cost_per_task is lower: -0.00006 to -0.00004; success holds: +0.000 to +0.000, no lower than -0.02

## Candidate 005, a change to 004: adopt
I tightened the schema shown to the model by removing redundant spaces before opening parentheses and just inside parentheses, while preserving quoted text, comments, and stored-value hints. This is intended to reduce input-token cost without changing the schema information or adding model calls. All 24 development tasks already passed, so this targets cost rather than a known failure; the savings have not been measured.

Changed: desk.py (+7 -1)
Decision: cost_per_task is lower: -0.00002 to -0.00001; success holds: +0.000 to +0.000, no lower than -0.02

## Candidate 006, a change to 005: screened
I shortened the fixed SQL-generation prompt and removed redundant blank lines to reduce input tokens on every question. The prompt still requests one read-only SQLite SELECT with no cosmetic aliases, and it receives the same schema and stored-value hints. All 24 development tasks already passed, so this targets cost rather than a known correctness failure; the savings have not been measured.

Changed: desk.py (+2 -4)
Decision: development cost_per_task 0.001336 is not below the base's 0.001329; validation was not run

