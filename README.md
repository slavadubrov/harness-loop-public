# harness-loop

A small Python library that improves an agent harness in a closed loop, with the model
held fixed. An improver, by default a coding agent, edits a copy of the harness. The
evaluator, [harness-evals](https://github.com/slavadubrov/harness-evals), scores the
candidate on tasks the improver cannot see. A rule keeps the change or drops it, and a
ledger records every candidate, kept or not.

It is the companion code for Part 5 of the
[Recursive Harness Engineering](https://slavadubrov.com/blog/) series.

- Python 3.12 or later. The only dependency is harness-evals, which has none.
- Built-in improvers are `claude_code` ([Claude Code](https://claude.com/claude-code) in its
  headless, restricted mode) and `openai_agent` (OpenAI `/v1/responses` over stdlib HTTP with
  workspace-confined file tools, selected via `--backend openai`). Any function or command that
  edits a directory can take their place.
- It does not call your model or run your harness: your adapter does, as in
  harness-evals.

## One step of the loop

1. **Propose.** The improver gets a workspace with a copy of the current harness, the
   development tasks it fails with sample runs, the history of earlier candidates and
   your reference material. It edits `harness/` and writes a note.
2. **Check the candidate.** No change, the same files as an earlier candidate, or a
   problem your `validate` function finds (a changed model, a copied task) ends the step
   without a run.
3. **Screen on development tasks.** A candidate that does not pass more development runs
   than the current harness is dropped. Its validation runs are skipped, so a change
   that cannot help costs no look at the validation tasks.
4. **Decide on validation tasks.** `harness_evals.compare(..., step=True)` pairs the
   candidate with the current harness task by task. The candidate is kept only if the
   whole interval of the success difference is above zero, clearly more tasks got better
   than worse, and no guardrail breaks.
5. **Record.** The ledger gets the note, the diff, the scores, the decision and its
   reasons, the improver's cost and the evaluation's cost.

The loop stops after `max_candidates` candidates, after `patience` candidates in a row
that were not kept, at a spending limit, or when no development task fails. Then the
starting harness and the final one are scored once on the test tasks.

Before the first step, the starting harness runs on the validation tasks a second time
with new samples, and the pair goes through the same rule (`noise.json`). Two runs of one
harness differ by noise alone, so the rule must answer "inconclusive". If it adopts or
rejects, it is too easy to satisfy on these tasks: add tasks or runs before trusting it.
A campaign whose noise check gets any other answer stops before its first step. The
rule's two conditions beyond the interval, higher success only and a sign test over the
tasks that changed, both come from pairs this check found.

## An example that replays offline: the SQL desk

[`examples/sql_desk/`](examples/sql_desk/) is a complete target. Its harness answers a
question about a shop's data with one SQL query; the evaluator runs the query and
compares the rows with a reference query's. The fixed model is OpenAI `gpt-6.2-sol`
(`reasoning_effort="low"`). The saved campaigns replay without a model:

```bash
git clone https://github.com/slavadubrov/harness-loop-public
cd harness-loop-public
uv run harness-loop report examples.sql_desk.target:TARGET examples/sql_desk/campaigns/run-1
uv run harness-loop show - examples/sql_desk/campaigns/run-1        # the ledger
uv run harness-loop show - examples/sql_desk/campaigns/run-1 002    # the kept candidate
```

| Saved campaign | Candidates | Kept | Test success, start to final | Difference on test |
| --- | --- | --- | --- | --- |
| `run-1`, with feedback | 2 | 1 | 0.58 to 0.90 | +0.315 (+0.167 to +0.463); 13 questions better, 0 worse |
| `run-2`, with feedback | 1 | 1 | 0.58 to 1.00 | +0.417 (+0.250 to +0.583); 15 better, 0 worse |
| `no-feedback-1`, a control | 3 | 0 | 0.58 | |
| `no-feedback-2`, a control | 3 | 0 | 0.58 | |

With feedback, the improver found from the development failures that the bare schema hides
stored enum, country, and category codes (such as `'canceled'`, `'pending_payment'`, `'NLD'`,
and `'audio_gear'`), and saw why an initial `sqlite_master` probe triggered SQLite authorizer
violations (`0.00` on dev). `run-1` recovered in Candidate `002` with a post-draft literal check
and repair loop; `run-2` parsed `db.schema()` directly in Candidate `001` to run a read-only
`SELECT DISTINCT` probe before drafting (`1.00` on test in one candidate). Without feedback,
both controls saw the `sqlite_master` candidate hit `0.00` on dev without seeing why, abandoned
database probing, and spent the rest of their budget on generic prompt checklists and `LIMIT 0`
syntax checks, keeping nothing. Each campaign's `REPORT.md` has every candidate with its note
and decision.

| In `examples/sql_desk/` | What it is |
| --- | --- |
| `seed/desk.py` | The starting harness: a prompt with the schema and one model call |
| `shop.py` | The environment: a SQLite database built from a fixed seed, read-only access, the OpenAI model client |
| `tasks.py` | 96 questions with reference queries: 24 development, 36 validation, 36 test |
| `target.py` | The use case, the adapter that runs a harness directory, the validity check, the `Target` |
| `runner.py` | Runs a harness on questions in a process of its own |
| `campaigns/` | Saved campaigns: with the evaluator's feedback, and controls without it |

To run a new campaign, export `OPENAI_API_KEY` and select the `openai` backend:

```bash
export OPENAI_API_KEY=...
uv run harness-loop run examples.sql_desk.target:TARGET runs/mine --backend openai --model gpt-6.2-sol --reasoning-effort medium --trials dev=3,val=3,test=3
uv run harness-loop run examples.sql_desk.target:TARGET runs/blind --no-feedback --backend openai --model gpt-6.2-sol --reasoning-effort medium --trials dev=3,val=3,test=3
```

`SQL_DESK_MODEL` and `SQL_DESK_REASONING_EFFORT` configure the executed SQL desk model.

## Install

```bash
uv add "harness-loop @ git+https://github.com/slavadubrov/harness-loop-public"
```

## Use it on your harness

Describe the use case for harness-evals with three splits: `dev` tasks, whose failures
the improver reads, `val` tasks, which decide whether a change is kept, and `test` tasks,
which are scored once at the end. Then describe the target:

```python
from pathlib import Path

from harness_loop import Target, campaign, openai_agent

TARGET = Target(
    usecase=USECASE,  # a harness_evals.UseCase with dev, val and test tasks
    seed=Path("my_harness"),  # the directory of the starting harness
    adapter=my_adapter,  # (harness directory) -> a harness-evals adapter
    frozen={"model": "gpt-6.2-sol"},
    brief="What the harness is for, and the limits a change must respect.",
    reference=Path("reference"),  # read-only material for the improver: API notes, policy
    validate=my_checks,  # (harness directory) -> a list of problems, or none
)

result = campaign(
    TARGET,
    openai_agent(model="gpt-6.2-sol", reasoning_effort="medium", step_budget_usd=2.0),
    "runs/first",
    max_candidates=8,
    patience=3,
    trials={"dev": 3, "val": 5, "test": 5},
)
print(result["stopped"], result["final"], result["test"])
```

`my_adapter(harness_dir)` returns the function harness-evals calls: it runs the harness in
that directory on a list of tasks and returns one `Episode` per task, built from what the
environment recorded. Put a trace in `Episode.extra`; the improver's feedback shows it.

The same from the command line, with the target in `my_target.py`:

```bash
harness-loop run my_target:TARGET runs/first --backend openai --model gpt-6.2-sol --reasoning-effort medium --step-budget-usd 2.0 --max-candidates 8
harness-loop show - runs/first            # the ledger, one line per candidate
harness-loop show - runs/first 003        # one candidate: decision, note and diff
harness-loop report my_target:TARGET runs/first   # rebuild REPORT.md and trajectory.svg
```

Run the same campaign command again after an interruption. Completed splits and recorded
proposals are reused. Once final test scoring starts, a restart finishes that selection.
Use one writer per campaign directory. The seed, screening settings, evaluator rules and
improver identity must match. Give a custom callable a JSON-serializable `describe`
attribute if its configuration affects what it proposes. New campaigns record these
settings. Older records can only verify the settings they stored.

`report` grades the saved episodes offline. It checks the manifest and the complete set
of task/trial pairs, recomputes the development screen, and compares candidates that
reached validation with their recorded parents. An unscored validity decision is marked
as recorded only. If revised checks now require validation that the campaign skipped,
the new decision is unverified. A regrade can describe only the candidates actually tried.
The report gives the recorded stopping reason and identifies the use case used for regrading.

`max_usd` limits the search between proposals. A proposal and its evaluation can take
the total over the limit. The optional final test costs extra. Reported totals include
candidate runs, the noise check, final tests and recorded failed proposal attempts.
Unknown costs are counted separately. For the SQL example, evaluation costs use the
`gpt-6.2-sol` API rates in `shop.py`.

## What the improver can see and change

The improver works in a temporary directory outside the campaign folder:

| In the workspace | What it is |
| --- | --- |
| `TASK.md` | Your brief and the rules of a step |
| `harness/` | A copy of the current harness: the only thing copied back |
| `feedback/dev.md` | The development tasks that fail, the failed checks and sample runs |
| `feedback/dev.jsonl` | Every development run in full |
| `history.md` | Earlier candidates: note, changed files, decision and reasons |
| `reference/` | Your read-only material |

The validation and test tasks, their runs, the checks' code and the campaign folder are
not in it. Both built-in improvers (`openai_agent` and `claude_code`) run with workspace-confined
file tools only and no tool that runs commands. The ledger records every refused path or tool
attempt. A custom `command` improver gets the same directory and no sandbox: confine it yourself.

A change outside `harness/` is thrown away. `validate` is where you reject a candidate
that changes what must stay fixed, such as the model, or that copies a development task
into the harness.

## What a campaign leaves on disk

```text
runs/first/
  campaign.json            what was held fixed: model, task fingerprints, runs per task
  ledger.jsonl             one row per candidate
  candidates/003/
    harness/               the candidate's files
    patch.diff, NOTE.md    what changed and why, in the improver's words
    seen/                  what the improver was shown
    dev/, val/             the runs, as harness-evals saves them
  candidates/000/val-again/  the starting harness's second validation run
  noise.json               the rule's answer on the starting harness against itself
  test/000/, test/003/     the starting and the final harness on the test tasks
  result.json, REPORT.md, trajectory.svg
```

## Improvers

| Improver | What it is |
| --- | --- |
| `openai_agent(model="gpt-6.2-sol", reasoning_effort="medium", step_budget_usd=2.0)` | OpenAI `/v1/responses` agent over stdlib HTTP (`--backend openai`), workspace-confined file tools, exact token pricing |
| `claude_code(model, budget_usd=2.0)` | Claude Code (`--backend claude`), headless and restricted; reports its cost at list price |
| `command(argv)` | Any command-line agent, run in the workspace; cost unknown, no sandbox |
| `scripted(steps)` | Prepared changes, one per step: tests, replays, a hand-written baseline |

An improver is a function `(workspace) -> Proposal`. Write your own in a few lines.

## A control: the same improver without feedback

`campaign(..., feedback=False)`, or `--no-feedback`, runs the same loop with the improver
shown only the harness, your brief and the notes of earlier candidates: no failing tasks,
no runs, no decisions. Candidates are scored and decided as before. Run it with the same
budget to see what the evaluator's feedback buys over the improver's own reading of the
code.

## Limits

- The adoption rule's intervals come from your validation tasks. With a few dozen tasks
  only a change that fixes several of them can be kept; smaller gains end as
  inconclusive. That is the rule working, and a reason to write more tasks.
- Every kept change was chosen because it scored well on the validation tasks, so the
  final harness's validation score is optimistic. Read the test score.
- The loop makes several decisions on the same validation tasks. `level` tightens each
  one; see the harness-evals README.
- The sandbox covers what the improver reads and writes while it proposes. A candidate's
  code runs with your adapter's permissions: run untrusted candidates in a container.
- The base's validation runs are reused for later comparisons, so the two sides of a
  comparison ran at different times.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

MIT licensed.
