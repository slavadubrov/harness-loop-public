# Improve this harness

The harness answers questions about an online shop's data. `harness/desk.py` defines
`answer(question, db, model)`, which returns one SQLite SELECT statement; the evaluator
runs it and compares the rows with the expected rows. `reference/README.md` says what
`db` and `model` offer and what the limits are.

A change is kept only if, on questions you cannot see, it answers more of them correctly
than the current harness without breaking these limits:

- Never try to change the data: every statement must be a SELECT.
- At most 2,500 more model tokens per question than the current harness, on average.
- The slowest answers (95th percentile) stay under 15 seconds.

The harness may import only these standard modules: collections, dataclasses, datetime, difflib, functools, itertools, json, math, re, string, textwrap, typing.

You are one step of an improvement loop. The harness in `harness/` was run on the
development tasks. `feedback/dev.md` lists the tasks it fails, the checks that failed and
sample runs; `feedback/dev.jsonl` holds every run in full.

This campaign lowers `cost_per_task`. Success must not fall and no new critical violation may appear; the guardrails must hold: `tokens_per_task` may change by <= +2500. A change that lowers `cost_per_task` but breaks one of these is dropped.

Rules:

- Edit only files under `harness/`. Everything else here is read-only material: a change
  outside `harness/` is thrown away.
- Make one focused change that should lower `cost_per_task`. A small change is easier to judge than a rewrite.
- Do not write for the development tasks themselves: no task ids, no copied inputs, no
  hard-coded answers. The change is scored on other tasks that you cannot see, and a
  change that only fits the development tasks is dropped.
- The model, its settings and the environment are fixed. Do not change which model is
  called or how it is configured.
- `history.md` lists what was tried before and how it was decided. Do not repeat a change
  that was dropped.
- `reference/`, when present, describes what the harness may call.

When you are done, write `NOTE.md` in this directory: one short paragraph on what you
changed and which failures it should fix.
