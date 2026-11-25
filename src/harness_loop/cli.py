"""harness-loop run|report|show module:TARGET folder
harness-loop frontier module:TARGET folder [folder ...] [--split val|test] [--out DIR]

``run`` starts or resumes a campaign, ``report`` rebuilds REPORT.md and trajectory.svg
from the saved runs, ``show`` prints the ledger or one candidate, and ``frontier``
compares the saved runs of several campaigns of one target.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

from harness_loop.improvers import claude_code, command, openai_agent
from harness_loop.loop import Target, campaign, read_ledger
from harness_loop.report import MARK, across, figures, report


def _target(ref: str) -> Target:
    module, _, attr = ref.partition(":")
    if os.getcwd() not in sys.path:  # a target next to the campaign, as a script would see it
        sys.path.insert(0, os.getcwd())
    try:
        target = getattr(importlib.import_module(module), attr or "TARGET")
    except (ImportError, AttributeError) as exc:
        raise SystemExit(f"{ref}: {exc}") from None
    if not isinstance(target, Target):
        raise SystemExit(f"{ref} is not a Target")
    return target


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["frontier"]:
        _frontier(argv[1:])
        return
    p = argparse.ArgumentParser(prog="harness-loop")
    p.add_argument("command", choices=["run", "report", "show"])
    p.add_argument("target", help="module:attribute of a Target; for show, any text")
    p.add_argument("out", type=Path, help="the campaign folder")
    p.add_argument("candidate", nargs="?", help="show: a candidate id such as 003")
    p.add_argument("--backend", choices=["openai", "claude"], default="openai")
    p.add_argument(
        "--model",
        default=None,
        help="run: improver model (default: gpt-6.2-sol for openai, sonnet for claude)",
    )
    p.add_argument("--reasoning-effort", default="medium", help="run: OpenAI improver reasoning")
    p.add_argument("--step-budget-usd", type=float, default=1.5, help="run: per-step USD budget")
    p.add_argument("--improver", help="run: a command to use instead of the built-in improver")
    p.add_argument("--max-candidates", type=int, default=8)
    p.add_argument("--patience", type=int, default=3)
    p.add_argument("--max-usd", type=float)
    p.add_argument("--level", type=float, default=0.95)
    p.add_argument("--trials", help="run: runs per task, for example dev=2,val=3,test=3")
    p.add_argument("--no-screen", action="store_true", help="run validation for every candidate")
    p.add_argument("--no-noise", action="store_true", help="skip the starting harness's second run")
    p.add_argument("--no-feedback", action="store_true", help="a control: show no run results")
    p.add_argument("--no-test", action="store_true", help="leave the test tasks unscored")
    p.add_argument("--objective", default="success", help="run: the metric a step improves")
    p.add_argument("--seed", type=Path, help="run: start from this harness directory")
    p.add_argument("--frontier", action="store_true", help="run: score the frontier on test")
    a = p.parse_args(argv)
    if a.command == "show":
        _show(a.out, a.candidate)
        return
    target = _target(a.target)
    if a.command == "run":
        if a.improver:
            improver = command(a.improver.split())
        elif a.backend == "claude":
            improver = claude_code(a.model or "sonnet", budget_usd=a.step_budget_usd)
        else:
            improver = openai_agent(
                a.model or "gpt-6.2-sol",
                reasoning_effort=a.reasoning_effort,
                budget_usd=a.step_budget_usd,
            )
        result = campaign(
            target,
            improver,
            a.out,
            max_candidates=a.max_candidates,
            patience=a.patience,
            max_usd=a.max_usd,
            level=a.level,
            screen=not a.no_screen,
            noise=not a.no_noise,
            feedback=not a.no_feedback,
            test=not a.no_test,
            objective=a.objective,
            seed=a.seed,
            frontier=a.frontier,
            trials={
                k: int(v) for k, v in (kv.split("=") for kv in (a.trials or "").split(",") if kv)
            },
        )
        print(f"Stopped: {result['stopped']}. Final harness: candidate {result['final']}.")
    print(report(target.usecase, a.out))


def _frontier(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="harness-loop frontier")
    p.add_argument("target", help="module:attribute of a Target")
    p.add_argument("folders", nargs="+", type=Path, help="campaign folders of that target")
    p.add_argument("--split", choices=["val", "test"], default="test")
    p.add_argument("--out", type=Path, help="write frontier-cost.svg and frontier-latency.svg")
    a = p.parse_args(argv)
    usecase = _target(a.target).usecase
    try:
        text, summaries = across(usecase, a.folders, a.split)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"harness-loop frontier: {exc}") from None
    print(text)
    if a.out:
        figures(summaries, a.out)


def _show(out: Path, cid: str | None) -> None:
    rows = read_ledger(out)
    if cid is None:
        for r in rows:
            val = f"{r['val']['success']:.2f}" if r["val"] else "  - "
            print(
                f"{r['id']}  {MARK.get(r['decision'], r['decision']):<16} val {val}  "
                + " ".join(r["note"].split())[:90]
            )
        return
    row = next((r for r in rows if r["id"] == cid), None)
    if row is None:
        raise SystemExit(f"no candidate {cid} in {out}")
    print(f"Candidate {cid}, a change to {row['parent']}: {row['decision']}")
    print("Why: " + "; ".join(row["reasons"]))
    print("\n" + row["note"].strip() + "\n")
    diff = out / "candidates" / cid / "patch.diff"
    print(diff.read_text() if diff.exists() else "(the starting harness has no diff)")


if __name__ == "__main__":
    main()
