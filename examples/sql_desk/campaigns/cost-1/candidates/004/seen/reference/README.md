# What the harness runs in

`answer(question, db, model)` is called once per question and returns one SQLite SELECT
statement as a string.

- `db.schema()` returns the raw `CREATE TABLE` statements from `sqlite_master` without
  documentation comments.
- `db.query(sql)` runs one SELECT on the live read-only database and returns at most 200
  rows as tuples. It raises `QueryError`, with SQLite's message, when the statement does
  not run. Every statement is recorded, and an attempt to change data is a violation.
- `model.complete(prompt, max_tokens=1024)` returns the model's reply as a string
  (pinned to `gpt-6.2-sol`, `reasoning_effort=low`). At most 6 calls per question; a
  repeated prompt gets a new sample.
- One question may take at most 90 seconds.

The expected rows come from a reference query. Rows are compared as sets (keeping a
consistent column order across all rows), in row order only when the question asks for
one; numbers are compared after rounding to two decimals. The database is open for
read-only `SELECT` inspection during `answer(...)` via `db.query(sql)`.
