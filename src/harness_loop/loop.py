"""Improve a harness in a closed loop with the model held fixed.

One step: an improver edits a copy of the current harness, the evaluator scores the
candidate on the development tasks and then on the validation tasks, and the adoption rule
keeps it or drops it. Every candidate goes into a ledger, kept or not. The test tasks are
scored once, after the last step.

The improver works in a directory that holds only what it may see: the harness, the
development feedback, the history and the target's reference material. The campaign
directory, with the validation and test runs, is somewhere else on disk.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness_evals import (
    Episode,
    Grade,
    UseCase,
    compare,
    digest,
    failures,
    fingerprint,
    gate_failures,
    load,
    run,
    save,
    summarize,
)
from harness_evals.compare import COMPARED
from harness_evals.metrics import LOWER_IS_BETTER, coordinate
from harness_evals.runner import Adapter

from harness_loop import __version__

TRIALS = {"dev": 3, "val": 5, "test": 5}
BASES = ("seed", "adopt")  # the decisions that make a candidate the base of later steps
KEPT = ("success", "pass^k", "violations", "cost_per_task", "latency_p95", "tokens_per_task")
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")

SEEN = (
    "The harness in `harness/` was run on the\ndevelopment tasks. `feedback/dev.md` lists"
    " the tasks it fails, the checks that failed and\nsample runs; `feedback/dev.jsonl`"
    " holds every run in full."
)
BLIND = "No results of earlier runs are available: improve the harness from its code alone."
GOAL = (
    "\n\nThis campaign lowers `{metric}`. Success must not fall and no new critical violation"
    " may appear{guardrails}. A change that lowers `{metric}` but breaks one of these is dropped."
)
# The axes of a frontier, with +1 where higher is better and -1 where lower is better.
AXES = {"success": 1, "cost_per_task": -1, "latency_p95": -1}

TASK = """# Improve this harness

{brief}

You are one step of an improvement loop. {feedback}{goal}

Rules:

- Edit only files under `harness/`. Everything else here is read-only material: a change
  outside `harness/` is thrown away.
- Make one focused change{target}. A small change is easier to judge than a rewrite.
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
"""


@dataclass
class Target:
    """What the loop improves and how to score it.

    ``usecase`` is a harness-evals use case whose tasks carry the splits ``dev``, ``val``
    and ``test``. ``seed`` is the directory of the starting harness. ``adapter`` turns a
    harness directory into a harness-evals adapter that runs it. ``frozen`` names what
    stays fixed, at least the model. ``reference`` is a directory of read-only material
    for the improver. ``validate`` returns the problems of a candidate directory before
    any run, for example a changed model. ``brief`` says what the harness is for."""

    usecase: UseCase
    seed: Path
    adapter: Callable[[Path], Adapter]
    frozen: dict[str, Any]
    brief: str = ""
    reference: Path | None = None
    validate: Callable[[Path], list[str]] | None = None


@dataclass
class Proposal:
    """What an improver reports about one change. The change itself is on disk."""

    note: str = ""
    cost_usd: float | None = None  # None means unknown, which is not the same as zero
    seconds: float | None = None
    model: str = ""
    denied: list[str] = field(default_factory=list)  # tool calls the sandbox refused
    error: str | None = None


Improver = Callable[[Path], Proposal]  # edits <workspace>/harness in place


class Finished(Exception):
    """Raised by an improver that has nothing more to propose."""


# -- harness directories -----------------------------------------------------------------


def files(root: Path) -> dict[str, bytes]:
    """Every file of a harness directory by relative path, without caches."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        cache = "__pycache__" in p.parts or p.suffix == ".pyc" or p.name == ".DS_Store"
        if p.is_file() and not cache:
            out[p.relative_to(root).as_posix()] = p.read_bytes()
    return out


def tree_id(tree: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for path, data in sorted(tree.items()):
        h.update(path.encode() + b"\0" + data + b"\0")
    return h.hexdigest()[:12]


def patch(old: dict[str, bytes], new: dict[str, bytes]) -> tuple[str, list[dict[str, Any]]]:
    """A unified diff of two harness directories, and the lines added and removed in
    each changed file."""
    text, changed = [], []
    for path in sorted(old.keys() | new.keys()):
        a, b = old.get(path, b""), new.get(path, b"")
        if a == b and (path in old) == (path in new):
            continue
        lines = list(
            difflib.unified_diff(
                a.decode(errors="replace").splitlines(keepends=True),
                b.decode(errors="replace").splitlines(keepends=True),
                f"a/{path}" if path in old else "/dev/null",
                f"b/{path}" if path in new else "/dev/null",
            )
        )
        text += [line if line.endswith("\n") else line + "\n" for line in lines]
        body = [line for line in lines if not line.startswith(("+++", "---"))]
        changed.append(
            {
                "path": path,
                "added": sum(line.startswith("+") for line in body),
                "removed": sum(line.startswith("-") for line in body),
            }
        )
    return "".join(text), changed


# -- the campaign --------------------------------------------------------------------------


def campaign(
    target: Target,
    improver: Improver,
    out: Path | str,
    *,
    max_candidates: int = 8,
    patience: int = 3,
    max_usd: float | None = None,
    trials: dict[str, int] | None = None,
    screen: bool = True,
    level: float = 0.95,
    test: bool = True,
    noise: bool = True,
    feedback: bool = True,
    objective: str = "success",
    seed: Path | str | None = None,
    frontier: bool = False,
) -> dict[str, Any]:
    """Run the loop until it stops, then score the starting and the final harness on the
    test tasks. Returns the result that is also written to ``<out>/result.json``.

    The loop stops after ``max_candidates`` candidates, after ``patience`` candidates in
    a row that were not adopted, when the improver's and the evaluation's known cost
    reaches ``max_usd``, or when no development task fails. ``screen`` skips the
    validation runs of a candidate that does not pass more development runs than the
    base, so each candidate that cannot help costs no look at the validation tasks.
    ``level`` is the confidence level of the adoption rule's intervals.

    ``noise`` runs the starting harness on the validation tasks a second time, with new
    samples, and puts the pair through the adoption rule (``<out>/noise.json``). Two runs
    of one harness differ by noise only, so any decision but "inconclusive" says the rule
    is too easy to satisfy on these tasks, and the campaign stops before its first step.
    ``feedback=False`` is a control: the improver gets the harness and the notes of
    earlier candidates, and no result of any run.

    ``objective`` is the metric a step must improve: success by default, or a metric where
    lower is better, such as ``cost_per_task``, while success, critical violations and the
    guardrails hold (see harness_evals.decide). With a latency objective the base runs on
    the validation tasks again next to each candidate. ``seed`` starts the campaign from
    another harness directory than ``target.seed``. ``frontier=True`` scores on the test
    tasks every harness that no other beats on success, cost per task and p95 latency
    (see non_dominated()), and lists them in the result as ``frontier``.

    A campaign resumes from its ledger: call it again with the same arguments. After the
    test tasks have been scored it does not step again, because they are no longer unseen.
    An improver that fails (an outage, a spending limit) stops the campaign at once, with
    the error in ``<out>/errors.jsonl`` and the test tasks unscored; resume it later.
    """
    out = Path(out)
    n = TRIALS | (trials or {})
    for split in n:
        if not target.usecase.split(split):
            raise ValueError(f"the use case has no tasks in split {split!r}")
    paired = (*COMPARED, *target.usecase.guardrails)
    if objective != "success" and not (objective in LOWER_IS_BETTER and objective in paired):
        known = ", ".join(m for m in dict.fromkeys(paired) if m in LOWER_IS_BETTER)
        raise ValueError(f"objective {objective!r}: use success or one of {known}")
    start = Path(seed) if seed is not None else target.seed
    seed_id = tree_id(files(start))
    _config(
        out,
        {
            "usecase": target.usecase.name,
            "usecase_version": target.usecase.version,
            "fingerprints": {s: fingerprint(target.usecase.split(s)) for s in n},
            "frozen": dict(target.frozen),
            "trials": n,
            "level": level,
            "seed": seed_id,
            **({"seed_dir": scrub(str(start))} if seed is not None else {}),
            "objective": objective,
            "noise": noise,
            "rule": {
                "gates": target.usecase.gates,
                "guardrails": target.usecase.guardrails,
                "margin": target.usecase.margin,
            },
            "screen": screen,
            "feedback": feedback,
            "improver": getattr(improver, "describe", None)
            or f"{getattr(improver, '__module__', type(improver).__module__)}."
            f"{getattr(improver, '__qualname__', type(improver).__qualname__)}",
            "harness_loop": __version__,
        },
    )
    ledger = out / "ledger.jsonl"
    rows = read_ledger(out)
    if (out / "result.json").exists():
        result = json.loads((out / "result.json").read_text())
        return result | {"spent": _spent(out, rows)}
    if not rows:
        seed = _harness(out, "000")
        if not seed.exists():
            with tempfile.TemporaryDirectory(dir=out) as tmp:
                staged = Path(tmp) / "harness"
                shutil.copytree(start, staged, ignore=SKIP)
                seed.parent.mkdir(parents=True, exist_ok=True)
                staged.rename(seed)
        if tree_id(files(seed)) != seed_id:
            raise ValueError(f"{seed}: saved seed differs from the starting harness")
        row = _blank("000", None)
        row.update(decision="seed", reasons=["the starting harness"])
        row["tree"] = seed_id
        _evaluate(target, out, row, n, None, level, screen=False, objective=objective)
        _append(ledger, rows, row)
    end = {"trials": n, "level": level, "objective": objective, "frontier": frontier}
    if (out / "finalizing.json").exists():
        pending = json.loads((out / "finalizing.json").read_text())
        return _finish(target, out, rows, pending, **end)
    # Older versions could be interrupted after opening the test set.
    if (out / "test").exists():
        pending = {"stopped": "resumed final test scoring", "final": _base(rows)["id"]}
        _write_json(out / "finalizing.json", pending)
        return _finish(target, out, rows, pending, **end)
    if noise:
        if not (out / "noise.json").exists():
            _noise(target, out, n["val"], level, objective)
        answer = json.loads((out / "noise.json").read_text())["decision"]
        if answer != "inconclusive":  # the rule would keep or reject noise: do not step
            reason = (
                f"the noise check failed: the rule answered {answer!r} on the starting harness"
                " against itself; add tasks or runs, or tighten the rule, then start again"
            )
            return {"stopped": reason, "final": _base(rows)["id"], "spent": _spent(out, rows)}
    while (
        stop := _stop(rows, max_candidates, patience, max_usd, _spent(out, rows), objective)
    ) is None:
        base = _base(rows)
        dev = _score(target, out, base["id"], "dev", n["dev"])
        row = _blank(f"{len(rows):03d}", base["id"])
        try:
            proposed = out / "candidates" / row["id"] / "proposal.json"
            if proposed.exists():
                row = json.loads(proposed.read_text())
            else:
                _propose(target, improver, out, rows, row, dev if feedback else None, objective)
                if row["decision"] != "error":
                    _write_json(proposed, row)
        except Finished:
            stop = "the improver has nothing more to propose"
            shutil.rmtree(out / "candidates" / row["id"], ignore_errors=True)
            break
        if row["decision"] == "error":
            # An improver that failed proposed nothing: it is not a candidate, it must not
            # count toward patience, and it must not send the campaign on to the test tasks.
            with open(out / "errors.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            shutil.rmtree(out / "candidates" / row["id"], ignore_errors=True)
            reason = f"the improver failed: {row['reasons'][0]}; run the campaign again to resume"
            return {"stopped": reason, "final": _base(rows)["id"], "spent": _spent(out, rows)}
        if not row["decision"]:
            _evaluate(target, out, row, n, base, level, screen, objective)
        _append(ledger, rows, row)
    result = {"stopped": stop, "final": _base(rows)["id"]}
    if test:
        _write_json(out / "finalizing.json", result)
        return _finish(target, out, rows, result, **end)
    return result | {"spent": _spent(out, rows)}


def _finish(
    target: Target,
    out: Path,
    rows: list[dict],
    result: dict,
    *,
    trials: dict[str, int],
    level: float,
    objective: str,
    frontier: bool,
) -> dict:
    final = _final(target, out, result["final"], trials["test"], level, objective)
    result = result | {"test": final}
    if frontier:
        result["frontier"] = _frontier(target, out, rows, trials)
    result["spent"] = _spent(out, rows)
    _write_json(out / "result.json", result)
    (out / "finalizing.json").unlink(missing_ok=True)
    return result


def _write_json(path: Path, data: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temp:
        temp.write(json.dumps(data, indent=2) + "\n")
    Path(temp.name).replace(path)


def read_ledger(out: Path | str) -> list[dict[str, Any]]:
    """Every candidate of a campaign, in order. Row 0 is the starting harness."""
    path = Path(out) / "ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _config(out: Path, config: dict[str, Any]) -> None:
    """Write the campaign's setup, or refuse to resume it under a different one."""
    path = out / "campaign.json"
    if path.exists():
        saved = json.loads(path.read_text())
        keys = (
            "usecase",
            "usecase_version",
            "fingerprints",
            "frozen",
            "trials",
            "level",
            "feedback",
            "screen",
            "improver",
        )
        # Old campaigns predate the objective: they optimized success.
        if saved.get("objective", "success") != config["objective"]:
            raise ValueError(f"{path} was started with a different objective; use a new folder")
        # Old campaigns predate seed, noise and rule metadata. Their ledger holds the seed.
        for key in (*keys, *(key for key in ("seed", "noise", "rule") if key in saved)):
            if saved.get(key) != json.loads(json.dumps(config[key])):
                raise ValueError(f"{path} was started with a different {key}; use a new folder")
        if "seed" not in saved and (seed := _harness(out, "000")).exists():
            if config["seed"] != tree_id(files(seed)):
                raise ValueError(f"{path} was started with a different seed; use a new folder")
        return
    out.mkdir(parents=True, exist_ok=True)
    _write_json(path, config | {"started": _now()})


def _blank(cid: str, parent: str | None) -> dict[str, Any]:
    return {
        "id": cid,
        "parent": parent,
        "decision": "",
        "reasons": [],
        "note": "",
        "files": [],
        "tree": "",
        "improver": None,
        "dev": None,
        "val": None,
        "delta": None,
        "eval": {"episodes": 0, "cost_usd": 0.0, "unknown_cost": 0, "seconds": 0.0},
        "at": _now(),
    }


def _harness(out: Path, cid: str) -> Path:
    return out / "candidates" / cid / "harness"


def _base(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return [r for r in rows if r["decision"] in BASES][-1]


def _append(ledger: Path, rows: list[dict[str, Any]], row: dict[str, Any]) -> None:
    rows.append(row)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _spent(out: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Known dollars and how many costs are unknown, for the improver and the runs."""
    errors = out / "errors.jsonl"
    attempts = rows + (
        [json.loads(line) for line in errors.read_text().splitlines()] if errors.exists() else []
    )
    props = [r["improver"] for r in attempts if r["improver"]]
    evaluations = [r["eval"] for r in rows]
    # The ledger holds candidate evaluations. Other phases keep their own episodes.
    for folder in [out / "candidates/000/val-again", *(out / "test").glob("*")]:
        if not (folder / "episodes.jsonl").exists():
            continue
        episodes = load(folder / "episodes.jsonl")
        manifest = json.loads((folder / "manifest.json").read_text())
        seconds = (
            datetime.fromisoformat(manifest["finished"])
            - datetime.fromisoformat(manifest["started"])
        ).total_seconds()
        evaluations.append(_eval_cost(episodes, seconds))
    return {
        "improver_usd": sum(p["cost_usd"] or 0.0 for p in props),
        "improver_unknown": sum(p["cost_usd"] is None for p in props),
        "improver_seconds": sum(p["seconds"] or 0.0 for p in props),
        "eval_usd": sum(e["cost_usd"] for e in evaluations),
        "eval_unknown": sum(e["unknown_cost"] for e in evaluations),
        "eval_seconds": sum(e["seconds"] for e in evaluations),
        "eval_episodes": sum(e["episodes"] for e in evaluations),
    }


def _stop(
    rows: list[dict[str, Any]],
    max_candidates: int,
    patience: int,
    max_usd: float | None,
    spent: dict,
    objective: str = "success",
) -> str | None:
    tried = rows[1:]
    if len(tried) >= max_candidates:
        return f"reached {max_candidates} candidates"
    streak = 0
    for r in reversed(tried):
        if r["decision"] == "adopt":
            break
        streak += 1
    if streak >= patience:
        return f"{patience} candidates in a row were not adopted"
    if max_usd is not None and spent["improver_usd"] + spent["eval_usd"] >= max_usd:
        return f"spent ${spent['improver_usd'] + spent['eval_usd']:.2f} of ${max_usd:.2f}"
    if objective == "success" and not _base(rows)["dev"]["failing"]:
        return "no development task fails"
    return None


def saved_episodes(
    folder: Path, cid: str, split: str, config: dict, usecase: UseCase
) -> list[Episode]:
    """Read one complete saved run, including each requested task on every trial."""
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"missing run manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    trials = config["trials"][split]
    required = {
        "harnesses": [cid],
        "split": split,
        "trials": trials,
        "fingerprint": config["fingerprints"][split],
        **{key: config[key] for key in ("frozen", "usecase", "usecase_version")},
    }
    for key, value in required.items():
        if manifest.get(key) != value:
            raise ValueError(f"{folder}: run manifest differs from the campaign's {key}")
    episodes = load(folder / "episodes.jsonl")
    expected = {(task.id, trial) for task in usecase.split(split) for trial in range(trials)}
    keys = {(episode.task_id, episode.trial) for episode in episodes}
    if (
        len(episodes) != len(expected)
        or keys != expected
        or any(episode.harness != cid for episode in episodes)
    ):
        raise ValueError(f"wrong or incomplete task and trial coverage: {folder}")
    return episodes


def _score(
    target: Target,
    out: Path,
    cid: str,
    split: str,
    trials: int,
    again: bool = False,
    folder: Path | None = None,
) -> list[Grade]:
    """Run a candidate on one split, or load the runs a resumed campaign already has.
    ``again`` takes new samples: the adapter gets trial numbers after the first ones.
    ``folder`` stores the runs somewhere other than the candidate's own folder."""
    if folder is None:
        folder = out / ("test" if split == "test" else "candidates") / cid
        folder = folder if split == "test" else folder / (split + "-again" * again)
    if (folder / "episodes.jsonl").exists():
        config = json.loads((out / "campaign.json").read_text())
        episodes = saved_episodes(folder, cid, split, config, target.usecase)
    else:
        adapter = target.adapter(_harness(out, cid))
        shifted = (lambda tasks, trial: adapter(tasks, trial + trials)) if again else adapter
        episodes = run(
            target.usecase,
            {cid: shifted},
            trials=trials,
            frozen=target.frozen,
            split=split,
            out=folder,
        )
    return target.usecase.grade(episodes)


def _noise(target: Target, out: Path, trials: int, level: float, objective: str) -> None:
    """The starting harness against itself on new samples of the validation tasks."""
    began = time.perf_counter()
    first = _score(target, out, "000", "val", trials)
    second = _score(target, out, "000", "val", trials, again=True)
    c = compare(target.usecase, first, second, step=True, level=level, objective=objective)
    result = {
        "decision": c.decision,
        "reasons": c.reasons,
        "delta": {k: [d[0], *d[1]] for k, d in c.deltas.items() if d and k in KEPT},
        "episodes": len(second),
        "seconds": round(time.perf_counter() - began, 1),
    }
    _write_json(out / "noise.json", result)


def _brief(usecase: UseCase, grades: list[Grade], objective: str = "success") -> dict[str, Any]:
    s = summarize(grades, usecase.metrics)
    out = {k: s[k] for k in KEPT} | {"success_ci": list(s["success_ci"]), "k": s["trials"]}
    if objective != "success":  # None while a cost is unknown for any run
        out[objective] = coordinate(s, objective)
    return out | {"failing": sorted(failures(grades))}


def screened(objective: str, dev: dict[str, Any], base: dict[str, Any]) -> str | None:
    """Why a candidate's development summary does not earn validation runs, or None.
    For success, it must pass more development runs than the base. For another objective,
    its value must be lower than the base's and its success no lower."""
    if objective == "success":
        if dev["success"] <= base["success"]:
            return (
                f"development success {dev['success']:.2f} is not above the base's"
                f" {base['success']:.2f}"
            )
        return None
    if dev["success"] < base["success"]:
        return f"development success {dev['success']:.2f} is below the base's {base['success']:.2f}"
    new, old = coordinate(dev, objective), coordinate(base, objective)
    if new is None or old is None or new >= old:
        return f"development {objective} {_value(new)} is not below the base's {_value(old)}"
    return None


def _value(v: float | None) -> str:
    return "unknown" if v is None else f"{v:.4g}"


def non_dominated(summaries: dict[str, dict[str, Any]]) -> list[str]:
    """The harnesses that no other beats on success, cost per task and p95 latency: none
    is at least as good on all three and better on one. Point estimates, as in
    harness_evals.metrics.pareto; a harness without one of the three is left out."""
    pts = {h: [coordinate(s, m) for m in AXES] for h, s in summaries.items()}
    known = {
        h: [v * sign for v, sign in zip(p, AXES.values(), strict=True)]
        for h, p in pts.items()
        if None not in p
    }
    return [
        h
        for h, a in known.items()
        if not any(
            b != a and all(x >= y for x, y in zip(b, a, strict=True))
            for o, b in known.items()
            if o != h
        )
    ]


def _propose(
    target: Target,
    improver: Improver,
    out: Path,
    rows: list[dict[str, Any]],
    row: dict[str, Any],
    dev: list[Grade] | None,
    objective: str = "success",
) -> None:
    """Let the improver edit a copy of the base, then file what it did. Sets a decision
    only when the candidate cannot be scored. ``dev`` is None when feedback is withheld."""
    folder = out / "candidates" / row["id"]
    shutil.rmtree(folder, ignore_errors=True)  # what an interrupted step left behind
    parent = _harness(out, row["parent"])
    with tempfile.TemporaryDirectory(prefix="harness-loop-") as tmp:
        ws = Path(tmp).resolve()
        shutil.copytree(parent, ws / "harness", ignore=SKIP)
        if target.reference:
            shutil.copytree(target.reference, ws / "reference", ignore=SKIP)
        if dev is not None:
            (ws / "feedback").mkdir()
            (ws / "feedback" / "dev.md").write_text(digest(target.usecase, dev, samples=2))
            save([g.episode for g in dev], ws / "feedback" / "dev.jsonl")
        (ws / "history.md").write_text(_history(rows, decisions=dev is not None))
        goal, aim = "", " that should fix failures listed in `feedback/dev.md`" * (dev is not None)
        if objective != "success":
            limits = [
                f"`{m}` may change by {op} {v:+g}"
                for m, (op, v) in target.usecase.guardrails.items()
            ]
            goal = GOAL.format(
                metric=objective,
                guardrails="; the guardrails must hold: " + "; ".join(limits) if limits else "",
            )
            aim = f" that should lower `{objective}`"
        task = TASK.format(
            brief=target.brief.strip(),
            feedback=SEEN if dev is not None else BLIND,
            goal=goal,
            target=aim,
        )
        (ws / "TASK.md").write_text(task)
        # What the improver saw, kept for the record. The harness is in the parent.
        shutil.copytree(
            ws, folder / "seen", ignore=lambda d, names: ["harness"] if Path(d) == ws else []
        )
        began = time.perf_counter()
        try:
            proposal = improver(ws)
        except Finished:
            raise
        except Exception as exc:  # noqa: BLE001 - a broken improver is a recorded candidate
            proposal = Proposal(error=scrub(repr(exc))[:500])
        if proposal.seconds is None:
            proposal.seconds = time.perf_counter() - began
        note = ws / "NOTE.md"
        row["note"] = proposal.note or (note.read_text() if note.exists() else "")
        shutil.copytree(ws / "harness", folder / "harness", ignore=SKIP)
    new = files(folder / "harness")
    diff, row["files"] = patch(files(parent), new)
    (folder / "patch.diff").write_text(diff)
    (folder / "NOTE.md").write_text(row["note"])
    proposal.note = ""  # the note is the row's
    row["improver"], row["tree"] = asdict(proposal), tree_id(new)
    same = next((r["id"] for r in rows if r["tree"] == row["tree"]), None)
    if proposal.error is not None:
        row.update(
            decision="error", reasons=[proposal.error or "improver failed without an error message"]
        )
    elif not row["files"]:
        row.update(decision="invalid", reasons=["the improver changed nothing in harness/"])
    elif same:
        row.update(decision="invalid", reasons=[f"the same files as candidate {same}"])
    elif target.validate and (problems := target.validate(folder / "harness")):
        row.update(decision="invalid", reasons=list(problems))


def _evaluate(
    target: Target,
    out: Path,
    row: dict[str, Any],
    n: dict[str, int],
    base: dict[str, Any] | None,
    level: float,
    screen: bool,
    objective: str = "success",
) -> None:
    """Score a candidate on development, then validation, and decide. ``base`` is None
    for the starting harness, which is scored and not decided."""
    uc = target.usecase
    began = time.perf_counter()
    graded: list[Grade] = []
    try:
        dev = _score(target, out, row["id"], "dev", n["dev"])
        graded += dev
        row["dev"] = _brief(uc, dev, objective)
        why = None
        if base and screen:
            old_dev = _score(target, out, base["id"], "dev", n["dev"])
            why = screened(objective, summarize(dev, uc.metrics), summarize(old_dev, uc.metrics))
        if why:
            row["decision"] = "screened"
            row["reasons"] = [f"{why}; validation was not run"]
        else:
            val = _score(target, out, row["id"], "val", n["val"])
            graded += val
            row["val"] = _brief(uc, val, objective)
            if base:
                if objective.startswith("latency"):  # both sides measured at about one time
                    folder = out / "candidates" / row["id"] / "val-base"
                    old = _score(target, out, base["id"], "val", n["val"], folder=folder)
                    graded += old
                else:
                    old = _score(target, out, base["id"], "val", n["val"])
                c = compare(uc, old, val, step=True, level=level, objective=objective)
                row["decision"], row["reasons"] = c.decision, c.reasons
                row["delta"] = {
                    k: [d[0], *d[1]] for k, d in c.deltas.items() if d and k in KEPT
                } | {"better": c.better, "worse": c.worse}
    finally:
        row["eval"] = _eval_cost([g.episode for g in graded], time.perf_counter() - began)


def _eval_cost(episodes: list[Episode], seconds: float) -> dict:
    costs = [e.cost_usd for e in episodes]
    return {
        "episodes": len(episodes),
        "cost_usd": sum(c for c in costs if c is not None),
        "unknown_cost": sum(c is None for c in costs),
        "seconds": round(seconds, 1),
    }


def _history(rows: list[dict[str, Any]], decisions: bool = True) -> str:
    base = _base(rows)["id"]
    lines = ["# Candidates so far", "", f"The harness in `harness/` is candidate {base}.", ""]
    if len(rows) == 1:
        lines.append("Nothing was tried yet: it is the starting harness.")
    for r in rows[1:]:
        changed = ", ".join(f"{f['path']} (+{f['added']} -{f['removed']})" for f in r["files"])
        title = f"## Candidate {r['id']}, a change to {r['parent']}"
        lines += [
            title + (f": {r['decision']}" if decisions else ""),
            r["note"].strip() or "(no note)",
            "",
            f"Changed: {changed or 'nothing'}",
            *(["Decision: " + "; ".join(r["reasons"])] if decisions else []),
            "",
        ]
    return "\n".join(lines) + "\n"


def _final(
    target: Target, out: Path, final: str, trials: int, level: float, objective: str
) -> dict[str, Any]:
    """Score the starting and the final harness on the test tasks, once."""
    uc = target.usecase
    seed = _score(target, out, "000", "test", trials)
    result: dict[str, Any] = {"000": _brief(uc, seed)}
    if final == "000":
        result["misses"] = gate_failures(summarize(seed, uc.metrics), uc.gates)
        return result
    best = _score(target, out, final, "test", trials)
    c = compare(uc, seed, best, step=True, level=level, objective=objective)
    result[final] = _brief(uc, best)
    result["delta"] = {k: [d[0], *d[1]] for k, d in c.deltas.items() if d and k in KEPT}
    result["decision"], result["reasons"] = c.decision, c.reasons
    result["misses"] = gate_failures(summarize(best, uc.metrics), uc.gates)  # the release bar
    return result


def _frontier(
    target: Target, out: Path, rows: list[dict[str, Any]], trials: dict[str, int]
) -> list[dict[str, Any]]:
    """The start and every candidate scored on validation that misses no gate the start
    clears and adds no critical violation; of those, the non_dominated() ones, each scored
    on the test tasks."""
    uc = target.usecase
    val = {r["id"]: _score(target, out, r["id"], "val", trials["val"]) for r in rows if r["val"]}
    sums = {cid: summarize(grades, uc.metrics) for cid, grades in val.items()}

    def missed(s: dict[str, Any]) -> set[str]:
        return {m for m, bar in uc.gates.items() if gate_failures(s, {m: bar})}

    start = sums["000"]
    fair = {
        cid: s
        for cid, s in sums.items()
        if missed(s) <= missed(start) and s["violations"] <= start["violations"]
    }
    return [
        {
            "id": cid,
            "val": _brief(uc, val[cid]),
            "test": _brief(uc, _score(target, out, cid, "test", trials["test"])),
        }
        for cid in non_dominated(fair)
    ]


def scrub(text: str) -> str:
    """Error text for the record, without this machine's directory names."""
    for path, name in (
        (Path.cwd(), "."),
        (Path.home(), "~"),
        (Path(tempfile.gettempdir()), "<tmp>"),
    ):
        text = text.replace(str(path.resolve()), name).replace(str(path), name)
    return text


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
