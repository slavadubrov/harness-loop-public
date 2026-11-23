"""Rebuild a saved campaign's numbers from its episodes: a Markdown report and one figure.

Nothing here calls a model. The episodes of every candidate are graded again with the use
case, each decision is taken again with the adoption rule and compared with the ledger.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from harness_evals import UseCase, compare, comparison, summarize, table

from harness_loop.loop import BASES, _spent, read_ledger, saved_episodes

MARK = {
    "seed": "start",
    "adopt": "adopted",
    "reject": "rejected",
    "inconclusive": "inconclusive",
    "screened": "screened on dev",
    "invalid": "invalid",
    "error": "error",
}


def regrade(usecase: UseCase, out: Path | str) -> dict[str, Any]:
    """The saved campaign graded again: one entry per candidate with its development and
    validation summaries, the decision taken now, and whether the ledger agrees."""
    out = Path(out)
    config = json.loads((out / "campaign.json").read_text())
    level = config["level"]
    rows = read_ledger(out)
    tried = max(len(rows) - 1, 1)

    def graded(folder, cid, split):
        episodes = saved_episodes(folder, cid, split, config, usecase)
        return usecase.grade(episodes)

    grades: dict[str, dict[str, Any]] = {}
    entries = []
    base = None
    for row in rows:
        cid, g = row["id"], {}
        for split in ("dev", "val"):
            path = out / "candidates" / cid / split / "episodes.jsonl"
            if path.exists():
                g[split] = graded(path.parent, cid, split)
            elif row.get(split) is not None or row["parent"] is None:
                raise ValueError(f"missing {split} episodes: {path}")
        grades[cid] = g
        entry = {"row": row, "decision": row["decision"], "comparison": None, "agrees": None}
        entry |= {s: summarize(gs, usecase.metrics) for s, gs in g.items()}
        parent = row["parent"]
        if parent is None:
            entry["decision"] = "seed"
        elif "dev" in g:
            if parent not in grades:
                raise ValueError(f"candidate {cid}: missing parent {parent}")
            base_dev = grades[parent]["dev"]
            if config["screen"] and entry["dev"]["success"] <= summarize(base_dev)["success"]:
                entry["decision"] = "screened"
                entry["reason"] = "development success did not exceed the parent's"
            elif "val" in g:
                base_val, val = grades[parent]["val"], g["val"]
                c = compare(usecase, base_val, val, step=True, level=level)
                entry["decision"], entry["comparison"] = c.decision, c
                strict = compare(usecase, base_val, val, step=True, level=1 - (1 - level) / tried)
                entry["strict"] = strict.decision
            else:
                entry["decision"] = "unverified"
                entry["reason"] = "the current screen requires validation; no validation runs exist"
        elif row["decision"] not in ("invalid", "error"):
            raise ValueError(f"candidate {cid}: missing development episodes")
        if "dev" in g and entry["decision"] != "unverified":
            entry["agrees"] = entry["decision"] == row["decision"]
        entry["base"] = base
        entry["off_path"] = parent is not None and parent != base
        if entry["decision"] in BASES and not entry["off_path"]:
            base = cid
        entries.append(entry)
    test = {}
    result_file = out / "result.json"
    recorded = json.loads(result_file.read_text()) if result_file.exists() else {}
    test_ids = {p.parent.name for p in (out / "test").glob("*/episodes.jsonl")}
    if "test" in recorded and test_ids != {"000", recorded["final"]}:
        raise ValueError("missing or unexpected final test runs")
    for cid in sorted(test_ids):
        test[cid] = graded(out / "test" / cid, cid, "test")
    noise, again = None, []
    path = out / "candidates" / "000" / "val-again" / "episodes.jsonl"
    if (out / "noise.json").exists() and not path.exists():
        raise ValueError("missing episodes from the recorded noise check")
    if path.exists():  # the starting harness against itself on new samples
        again = graded(path.parent, "000", "val")
        noise = compare(usecase, grades["000"]["val"], again, step=True, level=level)
    result = {
        "config": config,
        "entries": entries,
        "test": test,
        "final": base,
        "recorded": recorded,
        "spent": _spent(out, rows),
    }
    return result | {"noise": noise, "again": again}


def report(usecase: UseCase, out: Path | str) -> str:
    """Write ``REPORT.md`` and ``trajectory.svg`` into the campaign folder and return the
    report's text."""
    out = Path(out)
    r = regrade(usecase, out)
    config, entries = r["config"], r["entries"]
    tried = entries[1:]
    adopted = sum(e["row"]["decision"] == "adopt" for e in tried)
    replay_adopted = sum(e["decision"] == "adopt" and not e["off_path"] for e in tried)
    spent = r["spent"]
    recorded = r["recorded"]
    stop_note = []
    if recorded:
        stop_note.append("- Recorded stop: " + recorded["stopped"])
        if recorded["stopped"] == "no development task fails":
            final_dev = next(e["dev"] for e in entries if e["row"]["id"] == recorded["final"])
            if final_dev["success"] < 1:
                stop_note.append(
                    "- Under the current checks, the recorded final harness still "
                    "fails development runs. This stopping condition no longer holds."
                )
    lines = [
        f"# Campaign on {config['usecase']}",
        "",
        f"- Saved use case: `{config['usecase']}` v{config['usecase_version']}. "
        f"Regraded with `{usecase.name}` v{usecase.version}.",
        f"- Model held fixed: `{config['frozen'].get('model')}`",
        f"- Runs per task: {config['trials']['dev']} on development, {config['trials']['val']}"
        f" on validation, {config['trials']['test']} on test",
        f"- Adoption rule: one step of a loop, intervals at {config['level']:.2%}",
        f"- The campaign proposed {len(tried)} candidates and adopted {adopted}. "
        f"Regrading supports {replay_adopted} on the recorded path.",
        f"- Improver: ${spent['improver_usd']:.2f} known cost in"
        f" {spent['improver_seconds'] / 60:.1f} minutes."
        + (
            f" Cost is unknown for {spent['improver_unknown']} attempts."
            if spent["improver_unknown"]
            else ""
        ),
        f"- Evaluation: {sum(e['row']['eval']['episodes'] for e in entries)} runs of candidates"
        f" in {sum(e['row']['eval']['seconds'] for e in entries) / 60:.1f} minutes, "
        f"{len(r['again'])} more for the noise check and"
        f" {sum(len(gs) for gs in r['test'].values())} on the test tasks",
        f"- All evaluation phases: {spent['eval_episodes']} runs, "
        f"${spent['eval_usd']:.4f} in reported costs."
        + (f" Cost is unknown for {spent['eval_unknown']} runs." if spent["eval_unknown"] else ""),
        *stop_note,
        *_noise(r["noise"]),
        *_strict(tried, config["level"]),
        "",
        "## Every candidate",
        "",
        "Development screens and validation decisions are recomputed from saved runs. "
        "A decision without grading evidence is marked as recorded only. "
        "Test scores describe the harnesses the campaign actually tested.",
        "",
        "| Candidate | Change to | Development success | Validation success | Difference on"
        " validation | Decision | Why |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        row, c = e["row"], e["comparison"]
        dev = f"{e['dev']['success']:.2f}" if "dev" in e else "not run"
        val = _rate(e["val"]) if "val" in e else "not run"
        diff = f"{c.diff:+.2f} ({c.ci[0]:+.2f} to {c.ci[1]:+.2f})" if c else ""
        why = e.get("reason") or "; ".join(c.reasons if c else row["reasons"])
        flag = ""
        if e["agrees"] is False or e["decision"] == "unverified":
            flag = f" (ledger: {row['decision']})"
        elif e["agrees"] is None:
            flag = " (recorded only)"
        if e["off_path"]:
            flag += " (parent differs under regrading)"
        lines.append(
            f"| {row['id']} | {row['parent'] or ''} | {dev} | {val} | {diff} |"
            f" {MARK.get(e['decision'], e['decision'])}{flag} | {why} |"
        )
    lines += ["", "## What each candidate changed", ""]
    for e in tried:
        row = e["row"]
        changed = ", ".join(f"`{f['path']}` (+{f['added']} −{f['removed']})" for f in row["files"])
        lines += [
            f"**{row['id']}** ({MARK.get(e['decision'], e['decision'])}). "
            + " ".join(row["note"].split()),
            f"Files: {changed or 'none'}. Diff: `candidates/{row['id']}/patch.diff`.",
            "",
        ]
    if r["test"]:
        sums = {cid: summarize(gs, usecase.metrics) for cid, gs in r["test"].items()}
        lines += ["## Test tasks, scored once", "", table(sums, list(usecase.metrics)), ""]
        lines += [*_by_tag(usecase, r["test"]), ""]
        if len(r["test"]) == 2:
            first, final = list(r["test"].values())
            lines += [
                comparison(compare(usecase, first, final, step=True, level=config["level"])),
                "",
            ]
    text = "\n".join(lines)
    (out / "REPORT.md").write_text(text)
    (out / "trajectory.svg").write_text(trajectory_svg(entries))
    return text


def _noise(c: Any) -> list[str]:
    if c is None:
        return []
    ok = "as it should be" if c.decision == "inconclusive" else "the rule is too easy here"
    return [
        "- Noise check, the starting harness against itself on new samples: success"
        f" {c.diff:+.2f} ({c.ci[0]:+.2f} to {c.ci[1]:+.2f}), {c.decision}: {ok}"
    ]


def _strict(tried: list[dict[str, Any]], level: float) -> list[str]:
    """Decisions that would change if the campaign's candidates shared one error rate."""
    if not tried:
        return []
    strict = 1 - (1 - level) / len(tried)
    moved = [
        f"{e['row']['id']} ({e['decision']} becomes {e['strict']})"
        for e in tried
        if e.get("strict") and e["strict"] != e["decision"]
    ]
    return [
        f"- With intervals at {strict:.2%}, sensitivity check across {len(tried)}"
        " candidates: " + ("the same decisions" if not moved else ", ".join(moved))
    ]


def _by_tag(usecase: UseCase, test: dict[str, Any]) -> list[str]:
    """Success on the test tasks by each task's first tag, one column per harness."""
    tag = {t.id: (t.tags[0] if t.tags else "") for t in usecase.tasks}
    tags = sorted({tag[g.episode.task_id] for gs in test.values() for g in gs})
    if len(tags) < 2:
        return []
    lines = ["| Tasks tagged | " + " | ".join(test) + " |", "|---" * (len(test) + 1) + "|"]
    for name in tags:
        cells = []
        for gs in test.values():
            mine = [g for g in gs if tag[g.episode.task_id] == name]
            tasks = len({g.episode.task_id for g in mine})
            cells.append(f"{sum(g.passed for g in mine) / len(mine):.2f} ({tasks} tasks)")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def _rate(s: dict[str, Any]) -> str:
    lo, hi = s["success_ci"]
    return f"{s['success']:.2f} ({lo:.2f}–{hi:.2f})"


# Light colours in the attributes; a reader whose system prefers dark gets the others.
_STYLE = (
    "<style>@media (prefers-color-scheme:dark){svg{fill:#e6edf3}.bg{fill:#0d1117}"
    ".mut{fill:#9da7b3}.grid{stroke:#30363d}.ink{stroke:#e6edf3}.dot{fill:#e6edf3}"
    ".hole{fill:#0d1117;stroke:#e6edf3}.keep{stroke:#3fb950}.kept{fill:#3fb950}}</style>"
)


def trajectory_svg(entries: list[dict[str, Any]], title: str = "") -> str:
    """Validation success of every candidate in the order it was proposed, with its 95%
    interval. A filled mark is a harness that became the base, a hollow one was dropped,
    and the stepped line is the base's success. A candidate without validation runs gets
    a tick on the axis."""
    w, h, left, right, top, bottom = 720, 380, 64, 24, 56, 64
    n = len(entries)
    step = (w - left - right) / max(n, 1)

    def px(i: int) -> float:
        return left + step * (i + 0.5)

    def py(v: float) -> float:
        return h - bottom - v * (h - top - bottom)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="system-ui,'
        f' sans-serif" font-size="12" fill="#1f2328" role="img">{_STYLE}',
        f'<rect class="bg" width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{left}" y="24" font-size="15" font-weight="600">'
        f"{escape(title or 'Validation success of every candidate')}</text>",
        f'<text class="mut" x="{left}" y="42" fill="#59636e">Filled: base under regrading. Hollow:'
        " other candidate. Tick: validation not run. Bars: 95% interval over tasks.</text>",
    ]
    for t in (0, 0.25, 0.5, 0.75, 1):
        y = py(t)
        out.append(
            f'<line class="grid" x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}"'
            ' stroke="#d1d9e0"/>'
            f'<text class="mut" x="{left - 8}" y="{y + 4:.1f}" text-anchor="end"'
            f' fill="#59636e">{t:.2f}</text>'
        )
    level, path = None, []
    for i, e in enumerate(entries):  # the base's success as a stepped line
        if e["decision"] in BASES and not e.get("off_path") and "val" in e:
            level = e["val"]["success"]
        if level is not None:
            path += [
                f"{px(i) - step / 2:.1f},{py(level):.1f}",
                f"{px(i) + step / 2:.1f},{py(level):.1f}",
            ]
    if path:
        out.append(
            f'<polyline class="keep" points="{" ".join(path)}" fill="none" stroke="#1a7f37"'
            ' stroke-width="2"/>'
        )
    for i, e in enumerate(entries):
        x, row = px(i), e["row"]
        label = MARK.get(e["decision"], e["decision"])
        out.append(
            f'<text x="{x:.1f}" y="{h - bottom + 18}" text-anchor="middle">{row["id"]}</text>'
            f'<text class="mut" x="{x:.1f}" y="{h - bottom + 34}" text-anchor="middle"'
            f' font-size="10.5" fill="#59636e">{escape(label)}</text>'
        )
        if "val" not in e:
            out.append(
                f'<line class="ink" x1="{x:.1f}" x2="{x:.1f}" y1="{h - bottom - 6}"'
                f' y2="{h - bottom + 2}" stroke="#1f2328" stroke-width="2"/>'
            )
            continue
        s = e["val"]
        (lo, hi), y = s["success_ci"], py(s["success"])
        out.append(
            f'<line class="ink" x1="{x:.1f}" x2="{x:.1f}" y1="{py(lo):.1f}" y2="{py(hi):.1f}"'
            ' stroke="#1f2328"/>'
        )
        if e["decision"] in BASES and not e.get("off_path"):
            out.append(f'<circle class="kept" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#1a7f37"/>')
        else:
            out.append(
                f'<circle class="hole" cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="#ffffff"'
                ' stroke="#1f2328" stroke-width="1.5"/>'
            )
        out.append(
            f'<text x="{x:.1f}" y="{py(hi) - 6:.1f}" text-anchor="middle"'
            f' font-size="11">{s["success"]:.2f}</text>'
        )
    return "".join(out) + "</svg>\n"
