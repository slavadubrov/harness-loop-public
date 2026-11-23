"""The SQL desk as a target for harness-loop: a second use case, unlike a support desk.

The harness answers a question about a shop's data by writing one SQL query. The checks
are deterministic: the evaluator runs the query on its own copy of the database and
compares the rows with the reference query's rows.

    uv run harness-loop run examples.sql_desk.target:TARGET runs/sql-desk
    uv run harness-loop report examples.sql_desk.target:TARGET examples/sql_desk/campaigns/run-1
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from functools import cache
from itertools import permutations
from math import floor
from pathlib import Path

from harness_evals import Action, Check, Episode, Grade, Task, UseCase, never

from examples.sql_desk.runner import MODEL, REASONING_EFFORT, URL
from examples.sql_desk.shop import Db, QueryError, build
from examples.sql_desk.tasks import QUESTIONS, Q
from harness_loop import Target, scrub

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BY_ID = {q.id: q for q in QUESTIONS}
# Official OpenAI API token rates (2026-11): (uncached_in, cached_in, cache_write, output).
# Unknown models stay unpriced (None), never silently $0.00.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "gpt-6.2-sol": (2e-6, 1e-7, 2.5e-6, 1e-5),
    "gpt-6.1-terra": (1e-6, 5e-8, 1.25e-6, 5e-6),
}
INFRA = re.compile(r"HTTP (?:429|5\d\d)|connection error|TimeoutError", re.I)
ALLOWED = {"__future__", "collections", "dataclasses", "datetime", "difflib", "functools"}
ALLOWED |= {"itertools", "json", "math", "re", "string", "textwrap", "typing"}

BRIEF = """\
The harness answers questions about an online shop's data. `harness/desk.py` defines
`answer(question, db, model)`, which returns one SQLite SELECT statement; the evaluator
runs it and compares the rows with the expected rows. `reference/README.md` says what
`db` and `model` offer and what the limits are.

A change is kept only if, on questions you cannot see, it answers more of them correctly
than the current harness without breaking these limits:

- Never try to change the data: every statement must be a SELECT.
- At most 2,500 more model tokens per question than the current harness, on average.
- The slowest answers (95th percentile) stay under 15 seconds.

The harness may import only these standard modules: {allowed}.
"""

ABOUT = """\
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
"""


def _cost(row: dict) -> float | None:
    rates = PRICES.get(MODEL)
    if rates is None:
        return None
    cached = row.get("cached_input_tokens", 0)
    cache_write = row.get("cache_write_tokens", 0)
    uncached = max(row["input_tokens"] - cached - cache_write, 0)
    return (
        uncached * rates[0]
        + cached * rates[1]
        + cache_write * rates[2]
        + row["output_tokens"] * rates[3]
    )


@cache
def _shop() -> Path:
    return build(Path(tempfile.mkdtemp(prefix="sql-desk-")) / "shop.sqlite")


def run_sql(sql: str | None) -> tuple[list[list] | None, str | None, bool]:
    """The rows of a statement on the evaluator's own database, SQLite's error if it does
    not run, and whether it tried to change data."""
    if not sql:
        return None, "no statement", False
    db = Db(_shop(), max_rows=60)  # no expected answer has more than 50 rows
    try:
        return [list(r) for r in db.query(sql)], None, False
    except QueryError as exc:
        return None, str(exc), db.log[-1]["name"] == "write"
    finally:
        db.close()


@cache
def expected(task_id: str) -> tuple:
    rows, error, _ = run_sql(BY_ID[task_id].sql)
    if rows is None:
        raise ValueError(f"the reference query of {task_id} does not run: {error}")
    return _norm(rows, BY_ID[task_id].ordered)


def _norm(rows: list, ordered: bool) -> tuple:
    def value(v: object) -> object:
        if isinstance(v, int | float) and not isinstance(v, bool):
            return floor(float(v) * 100 + 0.5 + 1e-7) / 100  # half up, as SQLite's ROUND
        return v.strip() if isinstance(v, str) else v

    out = [tuple(value(v) for v in row) for row in rows]
    return tuple(out if ordered else sorted(out, key=repr))


@cache
def _column_orders(task_id: str) -> frozenset[tuple]:
    """Valid column orders for this reference answer. Each order applies to every row."""
    rows = expected(task_id)
    if not rows:
        return frozenset({()})
    orders = permutations(range(len(rows[0])))
    return frozenset(
        _norm([[row[i] for i in order] for row in rows], BY_ID[task_id].ordered) for order in orders
    )


def _matches(q: Q) -> Check:
    def fn(e: Episode) -> bool:
        rows = e.extra.get("rows")
        return rows is not None and _norm(rows, q.ordered) in _column_orders(q.id)

    return Check("answers with the expected rows", fn)


def valid_sql(grades: list[Grade]) -> float | None:
    """The share of runs whose final statement ran at all."""
    return statistics.fmean(g.episode.extra.get("rows") is not None for g in grades)


USECASE = UseCase(
    name="sql-desk",
    version="3",
    tasks=[
        Task(q.id, q.question, (_matches(q), never("write")), split=q.split, tags=(q.level,))
        for q in QUESTIONS
    ],
    # The bar the final harness must clear. Set before the first run.
    gates={"violations": ("<=", 0), "success": (">=", 0.8), "latency_p95": ("<=", 15.0)},
    metrics={"valid sql": valid_sql},
    margin=0.02,
    guardrails={"tokens_per_task": ("<=", 2500.0)},
)


def adapter(harness: Path):
    """Run the harness in a new process, then run each returned query here."""

    def run_tasks(tasks: list[Task], trial: int) -> list[Episode]:
        with tempfile.TemporaryDirectory(prefix="sql-desk-run-") as tmp:
            asked, out = Path(tmp) / "tasks.json", Path(tmp) / "out.json"
            asked.write_text(json.dumps([{"id": t.id, "question": t.input} for t in tasks]))
            cmd = [sys.executable, "-m", "examples.sql_desk.runner"]
            cmd += [str(harness), str(asked), str(out), str(trial)]
            r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
            if r.returncode:  # the harness does not load: its failure, on every question
                error = scrub(r.stderr.strip())[-600:]
                return [Episode(t.id, status="error", error=error) for t in tasks]
            episodes = []
            for row in json.loads(out.read_text()):
                rows, sql_error, wrote = run_sql(row["sql"])
                actions = [Action(a["name"], {"sql": a["sql"], "ok": a["ok"]}) for a in row["log"]]
                if wrote:
                    actions.append(Action("write", {"sql": row["sql"], "ok": False}))
                want = [list(r) for r in expected(row["id"])]
                episodes.append(
                    Episode(
                        row["id"],
                        status="error" if row["error"] else "completed",
                        reply=row["sql"],
                        actions=actions,
                        cost_usd=_cost(row),
                        latency_s=row["latency_s"],
                        input_tokens=row["input_tokens"],
                        output_tokens=row["output_tokens"],
                        model_calls=row["calls"],
                        models=[MODEL],
                        error=row["error"],
                        infra_error=bool(row["error"] and INFRA.search(row["error"])),
                        extra={
                            "rows": rows,
                            "sql_error": sql_error,
                            "expected_rows": len(want),
                            "expected_first_rows": want[:5],
                        },
                    )
                )
            return episodes

    return run_tasks


def validate(harness: Path) -> list[str]:
    """Why a candidate may not run: it does not parse, imports something outside the
    allowed modules, or copies a development question."""
    problems = []
    if not (harness / "desk.py").exists():
        return ["desk.py is missing"]
    dev = [q for q in QUESTIONS if q.split == "dev"]
    local = {p.stem for p in harness.glob("*.py")}
    for path in sorted(harness.rglob("*.py")):
        text = path.read_text(errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            problems.append(f"{path.name}: {exc.msg} (line {exc.lineno})")
            continue
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                names.add(n.module.split(".")[0])
        if bad := sorted(names - ALLOWED - local):
            problems.append(f"{path.name} imports {', '.join(bad)}")
        if copied := [q.id for q in dev if q.id in text or q.question[:40] in text]:
            problems.append(f"{path.name} copies development questions: {', '.join(copied[:3])}")
    return problems


def reference(out: Path) -> Path:
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    (out / "README.md").write_text(ABOUT)
    return out


TARGET = Target(
    usecase=USECASE,
    seed=HERE / "seed",
    adapter=adapter,
    frozen={
        "model": MODEL,
        "endpoint": URL,
        "reasoning_effort": REASONING_EFFORT,
        "sampling": (
            f"API defaults; reasoning_effort={REASONING_EFFORT}; seed from the trial number"
        ),
    },
    brief=BRIEF.format(allowed=", ".join(sorted(ALLOWED - {"__future__"}))),
    reference=reference(REPO / "build" / "sql-desk-reference"),
    validate=validate,
)
