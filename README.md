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

## Objectives: success, cost or latency

By default each step must raise success. `campaign(..., objective="cost_per_task")`, or
`--objective cost_per_task`, makes each step lower another metric instead:
`cost_per_task`, `latency_p50`, `latency_p95`, `calls_per_task`, `tokens_per_task`, or a
guardrail metric where lower is better. The campaign records the objective in
`campaign.json`, and a resumed campaign must use the same one.

- The improver's `TASK.md` names the metric to lower and says that success, critical
  violations and the guardrails must hold.
- The development screen drops a candidate unless its development value of the objective
  is lower than the base's and its development success is not lower.
- `harness_evals.compare(..., step=True, objective=...)` decides on validation. It adopts
  only if the whole interval of the objective is below zero, and success holds within the
  use case's `margin`.
- The noise check compares the starting harness with itself under the same objective.
  Two runs of one harness differ in cost and latency by sampling alone.
- The stop "no development task fails" applies to success only. A cost campaign stops on
  `max_candidates`, `patience` or `max_usd`.

Latency depends on the provider's load at the time of the run. With a latency objective,
the base runs on the validation tasks again right after each candidate, into
`candidates/<id>/val-base/`, and the comparison uses that run. This doubles the
validation runs of each step that reaches validation. The other objectives reuse the
base's saved validation runs.

`seed=Path(...)`, or `--seed DIR`, starts a campaign from another harness directory than
`Target.seed`, such as the kept harness of an earlier campaign. `campaign.json` records
its tree id and its directory.

```bash
harness-loop run my_target:TARGET runs/cheaper --objective cost_per_task --seed runs/first/candidates/003/harness
```

## The frontier: harnesses no other beats

One objective gives one final harness. `campaign(..., frontier=True)`, or `--frontier`,
also lists the harnesses a person may choose between. After the loop stops, it takes the
start and every candidate scored on validation that misses no gate the start clears and
adds no critical violation. Of those it keeps each harness that no other beats on
validation success, cost per task and p95 latency: a harness is dropped only if another
is at least as good on all three and better on one. These are point estimates, as in
`harness_evals.metrics.pareto`. Each member is scored on the test tasks, `result.json`
lists them under `frontier`, and `REPORT.md` gets a table of their validation and test
scores and two figures, `frontier-cost.svg` and `frontier-latency.svg`. Without the flag,
only the start and the final harness are scored on test.

`harness-loop frontier` does the same across saved campaigns of one target, with no
model calls. It requires the same frozen setup and task fingerprints in every campaign,
counts a harness that several campaigns ran once, by its tree id, and marks the
harnesses no other beats. `--split val` reads the validation runs instead of the test
runs, and `--out DIR` writes the two figures.

```bash
uv run harness-loop frontier examples.sql_desk.target:TARGET examples/sql_desk/campaigns/run-1 examples/sql_desk/campaigns/run-2 examples/sql_desk/campaigns/no-feedback-1 examples/sql_desk/campaigns/no-feedback-2 --split test
```

| Harness | Tree | Success | $ per task | p95 latency, s | Tokens per task | Frontier |
|---|---|---|---|---|---|---|
| run-1/000 | 8f98ba16d651 | 0.58 | $0.00130 | 3.04 | 414 | yes |
| run-1/002 | 3ea1a583dd85 | 0.90 | $0.00151 | 3.94 | 506 | yes |
| run-2/001 | eba8e62509ad | 1.00 | $0.00187 | 3.29 | 650 | yes |

On these test runs the start is the cheapest and the fastest, and `run-2/001` is the
most successful. `run-1/002` is cheaper than `run-2/001` and more successful than the
start.

## An example that replays offline: the SQL desk

[`examples/sql_desk/`](examples/sql_desk/) is a complete target. Its harness answers a
question about a shop's data with one SQL query; the evaluator runs the query and
compares the rows with a reference query's. The fixed model is OpenAI `gpt-6.2-sol`
(`reasoning_effort="low"`). Use [uv](https://docs.astral.sh/uv/) to regrade the saved
runs without a model or API key. The first invocation installs dependencies.
`report` regenerates the campaign's local report and figure, and `show` reads its ledger.

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

Two more saved campaigns start from the harness that `run-2` kept (`--seed`) and optimize
another metric while success holds. Both ran with `--frontier`.

| Saved campaign | Candidates | Kept | On test, start to final |
| --- | --- | --- | --- |
| `cost-1`, `--objective cost_per_task` | 8 | 7 | Success stays at 1.00. Cost per question $0.00186 to $0.00137, tokens 650 to 447 |
| `latency-1`, `--objective latency_p95` | 3 | 0 | Unchanged. No candidate's p95 latency interval was below zero |

In `cost-1` every kept change shortens the prompt: a shorter instruction, a compact
schema, shorter stored-value hints. In `latency-1` two runs of the starting harness
differed in p95 latency by -0.37 to +0.07 seconds, and no candidate moved it by more.
Across all six campaigns, three harnesses are on the frontier on the test questions:

```bash
uv run harness-loop frontier examples.sql_desk.target:TARGET examples/sql_desk/campaigns/* --split test
```

| Harness | Success | $ per task | p95 latency, s |
| --- | --- | --- | --- |
| `run-1/000`, the start | 0.58 | $0.00130 | 3.04 |
| `cost-1/008` | 1.00 | $0.00137 | 3.22 |
| `latency-1/001`, not kept by the rule | 1.00 | $0.00177 | 2.78 |

The frontier uses point estimates. The latency difference that puts `latency-1/001` on
it is within the noise the campaign measured.

The database stores values such as `pending_payment` and `NLD`. A query that guesses
`pending` or `Netherlands` can execute successfully and still return the wrong rows.
All four campaigns proposed looking up stored values on their first attempt.

- In `run-1` and both controls, the first candidate used SQLite's `pragma_table_info`
  to find text columns. The read-only authorizer blocked the operation initiated by
  that helper and recorded a violation. All 72 development runs failed, so those
  candidates were screened out before validation.
- In `run-1`, the improver saw the development score drop and the current harness's
  failures on guessed values. Its next candidate checked text literals after drafting
  the SQL and asked the model to repair missing values only when needed.
- In `run-2`, the first candidate already used the available schema and a read-only
  `SELECT` to collect stored values before drafting. Both adopted changes improved
  nine of 36 validation questions and worsened none.
- The controls saw their own notes and the unchanged harness. They switched to prompt
  advice or syntax checks, and none of those candidates was kept.

The two controls also found the underlying problem. The clearest difference appeared
after the first candidate failed, when the first feedback campaign tried a different
way to look up the same values. These are four campaigns on one synthetic database.
See the saved reports for [feedback run 1](examples/sql_desk/campaigns/run-1/REPORT.md),
[feedback run 2](examples/sql_desk/campaigns/run-2/REPORT.md),
[control 1](examples/sql_desk/campaigns/no-feedback-1/REPORT.md), and
[control 2](examples/sql_desk/campaigns/no-feedback-2/REPORT.md).

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
harness-loop frontier my_target:TARGET runs/first runs/cheaper --out runs/frontier
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
  frontier-*.svg           with --frontier: success against cost and against latency
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
shown the current harness, your brief, any reference material and the notes of earlier
candidates. The loop withholds failing tasks, runs, scores and decisions. The unchanged
harness can still reveal that a proposal was dropped. Candidates are scored and decided
as before. Run it with the same
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
  comparison ran at different times. A latency objective runs the base again instead.
- The frontier uses point estimates. Harnesses whose intervals overlap may change places
  in another sample.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

MIT licensed.
