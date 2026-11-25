import importlib.util
import json
from pathlib import Path

import pytest
from harness_evals import Episode, Task, UseCase, says

from harness_loop import (
    Finished,
    Proposal,
    Target,
    campaign,
    files,
    patch,
    read_ledger,
    regrade,
    report,
    scripted,
)
from harness_loop.cli import main
from harness_loop.improvers import _local

# The toy use case: reply with the word reversed. The starting harness echoes the word,
# so it passes only the palindromes.
WORDS = {
    "dev": ["level", "stone", "river", "cloud", "noon", "table"],
    "val": ["radar", "paper", "green", "house", "civic", "light", "mouse", "plant"],
    "test": ["rotor", "stars", "bread", "chair", "kayak", "floor", "grape", "water"],
}
SEED = "def reply(word):\n    return word\n"
REVERSE = "def reply(word):\n    return word[::-1]\n"


def usecase(**kw) -> UseCase:
    tasks = [
        Task(w, w, (says(f"^{w[::-1]}$"),), split=split, tags=("same" if w == w[::-1] else "new",))
        for split, ws in WORDS.items()
        for w in ws
    ]
    return UseCase("reverse", tasks, **kw)


def adapter(harness: Path):
    def run_tasks(tasks, trial):
        spec = importlib.util.spec_from_file_location("candidate", harness / "harness.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cost, latency = getattr(module, "COST", 0.001), getattr(module, "LATENCY", 0.1)
        return [
            Episode(t.id, reply=module.reply(t.input), cost_usd=cost, latency_s=latency)
            for t in tasks
        ]

    return run_tasks


def target(tmp_path: Path, **kw) -> Target:
    seed = tmp_path / "seed"
    seed.mkdir(exist_ok=True)
    (seed / "harness.py").write_text(SEED)
    return Target(usecase(), seed, adapter, {"model": "none"}, brief="Reverse the word.", **kw)


def write(code: str, note: str):
    def step(harness: Path) -> str:
        (harness / "harness.py").write_text(code)
        return note

    return step


def test_a_campaign_adopts_a_real_improvement_and_drops_the_rest(tmp_path):
    steps = [
        write(SEED + "\n", "a blank line"),
        write(SEED + "\n", "the blank line again"),
        write(SEED, "back to the start"),
        write("def reply(word):\n    return ''\n", "reply with nothing"),
        write(REVERSE, "reverse the word"),
    ]
    out, n = tmp_path / "run", {"dev": 2, "val": 2, "test": 2}
    result = campaign(target(tmp_path), scripted(steps), out, trials=n, patience=5)
    rows = read_ledger(out)
    assert [r["decision"] for r in rows] == [
        "seed",
        "screened",
        "invalid",
        "invalid",
        "screened",
        "adopt",
    ]
    assert rows[1]["val"] is None  # a screened candidate costs no look at validation
    assert "candidate 001" in rows[2]["reasons"][0] and rows[2]["eval"]["episodes"] == 0
    assert rows[3]["reasons"] == ["the improver changed nothing in harness/"]
    assert rows[5]["parent"] == "000" and rows[5]["delta"]["success"][1] > 0
    assert rows[5]["delta"]["better"] and not rows[5]["delta"]["worse"]
    assert result["stopped"] == "no development task fails" and result["final"] == "005"
    assert result["test"]["000"]["success"] == 0.25 and result["test"]["005"]["success"] == 1.0
    assert result["test"]["decision"] == "adopt" and result["test"]["misses"] == []
    diff = (out / "candidates" / "005" / "patch.diff").read_text()
    assert diff.count("+    return word[::-1]") == 1
    # The test tasks are scored once: a second call returns the saved result and runs nothing.
    assert campaign(target(tmp_path), scripted([]), out, trials=n, patience=5) == result


def test_the_improver_sees_feedback_and_history_but_not_validation_or_test(tmp_path):
    seen = {}

    def look(workspace: Path) -> Proposal:
        seen["files"] = sorted(files(workspace))
        seen["text"] = "".join(p.read_text() for p in workspace.rglob("*") if p.is_file())
        seen["inside_campaign"] = (tmp_path / "run") in workspace.parents
        (workspace / "TASK.md").write_text("changed")  # outside harness/: thrown away
        (workspace / "harness" / "harness.py").write_text(REVERSE)
        (workspace / "NOTE.md").write_text("reverse it")
        return Proposal(cost_usd=0.5)

    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / "API.md").write_text("reply(word) returns a string")
    campaign(target(tmp_path, reference=ref), look, tmp_path / "run", max_candidates=1, test=False)
    assert seen["files"] == [
        "TASK.md",
        "feedback/dev.jsonl",
        "feedback/dev.md",
        "harness/harness.py",
        "history.md",
        "reference/API.md",
    ]
    assert "stone" in seen["text"] and "Reverse the word." in seen["text"]
    hidden = WORDS["val"] + WORDS["test"]
    assert not any(w in seen["text"] for w in hidden) and not seen["inside_campaign"]
    row = read_ledger(tmp_path / "run")[1]
    assert row["note"] == "reverse it" and row["improver"]["cost_usd"] == 0.5
    assert [f["path"] for f in row["files"]] == ["harness.py"]
    assert not (tmp_path / "run" / "result.json").exists()  # test=False leaves the test unseen


def test_a_campaign_stops_on_patience_budget_and_a_finished_improver(tmp_path):
    def worse(i):
        return write(f"def reply(word):\n    return '{i}'\n", f"always {i}")

    kw = {"trials": {"dev": 1, "val": 1, "test": 1}, "test": False}
    r = campaign(
        target(tmp_path), scripted(worse(i) for i in range(9)), tmp_path / "a", patience=2, **kw
    )
    assert r["stopped"] == "2 candidates in a row were not adopted"
    r = campaign(target(tmp_path), scripted([worse(1)]), tmp_path / "b", **kw)
    assert r["stopped"] == "the improver has nothing more to propose"
    assert [x["id"] for x in read_ledger(tmp_path / "b")] == ["000", "001"]

    def paid(workspace: Path) -> Proposal:
        (workspace / "harness" / "harness.py").write_text("def reply(word):\n    return 'x'\n")
        return Proposal(cost_usd=3.0)

    r = campaign(target(tmp_path), paid, tmp_path / "c", max_usd=2.0, **kw)
    assert r["stopped"].startswith("spent $3.0") and len(read_ledger(tmp_path / "c")) == 2


def test_a_broken_improver_and_an_invalid_candidate_are_recorded_not_scored(tmp_path):
    def broken(workspace: Path) -> Proposal:
        raise RuntimeError("no network")

    kw = {"trials": {"dev": 1, "val": 1, "test": 1}, "max_candidates": 1}
    broken.describe = {"kind": "test improver"}
    r = campaign(target(tmp_path), broken, tmp_path / "a", **kw)
    # A failed improver is not a candidate: the campaign stops, the test stays unscored,
    # and the next call picks up where it stopped.
    assert r["stopped"].startswith("the improver failed") and "no network" in r["stopped"]
    assert len(read_ledger(tmp_path / "a")) == 1 and not (tmp_path / "a" / "result.json").exists()
    assert "no network" in (tmp_path / "a" / "errors.jsonl").read_text()
    assert not (tmp_path / "a" / "candidates" / "001").exists()
    recovered = scripted([write(REVERSE, "reverse")])
    recovered.describe = broken.describe
    r = campaign(target(tmp_path), recovered, tmp_path / "a", **kw)
    assert r["final"] == "001" and (tmp_path / "a" / "result.json").exists()
    kw["test"] = False

    t = target(tmp_path, validate=lambda d: ["calls another model"])
    campaign(t, scripted([write(REVERSE, "reverse")]), tmp_path / "b", **kw)
    row = read_ledger(tmp_path / "b")[1]
    assert row["decision"] == "invalid" and row["reasons"] == ["calls another model"]
    assert row["eval"]["episodes"] == 0


def test_a_campaign_resumes_from_its_ledger_and_refuses_a_changed_setup(tmp_path):
    kw = {"trials": {"dev": 1, "val": 1, "test": 1}, "test": False}
    out = tmp_path / "run"
    bad = write("def reply(word):\n    return ''\n", "nothing")
    campaign(target(tmp_path), scripted([bad]), out, max_candidates=1, **kw)
    (out / "candidates" / "002" / "seen").mkdir(parents=True)  # a step that was interrupted
    r = campaign(
        target(tmp_path), scripted([write(REVERSE, "reverse")]), out, max_candidates=2, **kw
    )
    assert [x["decision"] for x in read_ledger(out)] == ["seed", "screened", "adopt"]
    assert r["final"] == "002"
    with pytest.raises(ValueError, match="different trials"):
        campaign(target(tmp_path), scripted([]), out, trials={"dev": 2, "val": 1, "test": 1})


def test_the_report_regrades_the_saved_runs_and_agrees_with_the_ledger(tmp_path, capsys):
    out = tmp_path / "run"
    steps = [
        write("def reply(word):\n    return word.upper()\n", "upper"),
        write(REVERSE, "reverse"),
    ]
    campaign(
        target(tmp_path), scripted(steps), out, trials={"dev": 1, "val": 1, "test": 1}, screen=False
    )
    r = regrade(usecase(), out)
    assert [e["decision"] for e in r["entries"]] == ["seed", "inconclusive", "adopt"]
    assert all(e["agrees"] for e in r["entries"]) and r["final"] == "002"
    text = report(usecase(), out)
    assert "| 002 | 000 | 1.00 | 1.00 (1.00–1.00) | +0.75 (" in text and "| adopted |" in text
    assert "## Test tasks, scored once" in text and "Decision: **adopt**" in text
    assert (out / "trajectory.svg").read_text().startswith("<svg")
    # A stricter use case decides differently, and the report says where the ledger differs.
    strict = usecase(gates={"success": (">=", 0.5)})
    assert [e["agrees"] for e in regrade(strict, out)["entries"]] == [True, True, True]
    main(["show", "-", str(out)])
    main(["show", "-", str(out), "002"])
    shown = capsys.readouterr().out
    assert "002  adopted" in shown and "+    return word[::-1]" in shown


def test_patch_counts_added_removed_and_new_files():
    diff, changed = patch(
        {"a.py": b"x\ny\n", "gone.py": b"z\n"}, {"a.py": b"x\nw\n", "new.py": b"n\n"}
    )
    assert changed == [
        {"path": "a.py", "added": 1, "removed": 1},
        {"path": "gone.py", "added": 0, "removed": 1},
        {"path": "new.py", "added": 1, "removed": 0},
    ]
    assert (
        "+++ b/new.py" in diff
        and "--- /dev/null" in diff
        and patch({"a": b"1"}, {"a": b"1"}) == ("", [])
    )


def test_scripted_raises_finished_when_it_runs_out(tmp_path):
    (tmp_path / "harness").mkdir()
    p = scripted([lambda harness: "one"])
    assert p(tmp_path).note == "one"
    with pytest.raises(Finished):
        p(tmp_path)
    assert json.dumps(p.describe)


def test_the_noise_check_runs_the_start_twice_and_the_rule_decides_nothing(tmp_path):
    seeds = []

    def adapter_with_seeds(harness: Path):
        inner = adapter(harness)

        def run_tasks(tasks, trial):
            seeds.append((tasks[0].split, trial))
            return inner(tasks, trial)

        return run_tasks

    t = target(tmp_path)
    t.adapter = adapter_with_seeds
    out, n = tmp_path / "run", {"dev": 1, "val": 2, "test": 1}
    campaign(t, scripted([]), out, trials=n, test=False)
    noise = json.loads((out / "noise.json").read_text())
    assert noise["decision"] == "inconclusive" and noise["delta"]["success"][0] == 0
    assert [trial for split, trial in seeds if split == "val"] == [0, 1, 2, 3]  # new samples
    assert "Noise check" in report(usecase(), out) and regrade(usecase(), out)["noise"]
    campaign(target(tmp_path), scripted([]), tmp_path / "quiet", trials=n, test=False, noise=False)
    assert not (tmp_path / "quiet" / "noise.json").exists()


def test_the_control_without_feedback_shows_no_result_of_any_run(tmp_path):
    seen = []

    def look(workspace: Path) -> Proposal:
        seen.append({p: (workspace / p).read_text() for p in files(workspace)})
        (workspace / "harness" / "harness.py").write_text(
            f"def reply(word):\n    return {len(seen)}\n"
        )
        return Proposal(note=f"try {len(seen)}")

    out, n = tmp_path / "run", {"dev": 1, "val": 1, "test": 1}
    campaign(target(tmp_path), look, out, max_candidates=2, trials=n, test=False, feedback=False)
    first, second = seen
    assert sorted(first) == ["TASK.md", "harness/harness.py", "history.md"]
    assert "No results of earlier runs" in first["TASK.md"] and "feedback/" not in first["TASK.md"]
    assert "try 1" in second["history.md"] and "Decision" not in second["history.md"]
    assert "screened" not in second["history.md"]
    with pytest.raises(ValueError, match="different feedback"):
        campaign(target(tmp_path), look, out, trials=n, test=False)


def test_the_report_shows_test_success_by_tag(tmp_path):
    out = tmp_path / "run"
    campaign(target(tmp_path), scripted([write(REVERSE, "reverse")]), out, trials={"dev": 1})
    text = report(usecase(), out)
    assert "| Tasks tagged | 000 | 001 |" in text
    assert "| new | 0.00 (6 tasks) | 1.00 (6 tasks) |" in text
    assert "| same | 1.00 (2 tasks) | 1.00 (2 tasks) |" in text
    assert "sensitivity check across 1 candidates: the same decisions" in text


def test_a_refused_call_is_recorded_without_the_machines_directory_names(tmp_path):
    call = {"path": str(tmp_path / "feedback" / "dev.md"), "file_path": "/etc/hosts", "n": 3}
    assert _local(call, tmp_path) == {
        "file_path": "<outside the workspace>///etc/hosts".replace("///", "/"),
        "n": 3,
        "path": "feedback/dev.md",
    }


def test_a_campaign_does_not_step_when_the_rule_keeps_noise(tmp_path):
    # The second sample of the same harness passes six more tasks: the rule keeps it.
    def lucky(harness: Path):
        def run_tasks(tasks, trial):
            ok = trial >= 1  # the noise check's second sample uses later trial numbers
            return [
                Episode(t.id, reply=t.input[::-1] if ok else t.input, cost_usd=0.0, latency_s=0.1)
                for t in tasks
            ]

        return run_tasks

    t = target(tmp_path)
    t.adapter = lucky
    out = tmp_path / "run"
    r = campaign(t, scripted([write(REVERSE, "reverse")]), out, trials={"dev": 1, "val": 1})
    assert r["stopped"].startswith("the noise check failed") and "'adopt'" in r["stopped"]
    assert len(read_ledger(out)) == 1 and not (out / "result.json").exists()


def test_the_record_of_what_the_improver_saw_keeps_nested_folders_named_harness(tmp_path):
    ref = tmp_path / "reference"
    (ref / "lab" / "harness").mkdir(parents=True)
    (ref / "lab" / "harness" / "spec.py").write_text("SPEC = 1\n")
    out, kw = tmp_path / "run", {"trials": {"dev": 1, "val": 1, "test": 1}, "test": False}
    campaign(target(tmp_path, reference=ref), scripted([write(REVERSE, "r")]), out, **kw)
    seen = out / "candidates" / "001" / "seen"
    assert (seen / "reference" / "lab" / "harness" / "spec.py").exists()
    assert not (seen / "harness").exists()


def test_replay_recomputes_dev_screen_and_requires_validation_evidence(tmp_path):
    t = target(tmp_path)
    out = tmp_path / "run"
    campaign(t, scripted([write(SEED + "\n", "blank")]), out, max_candidates=1, test=False)
    rows = read_ledger(out)
    rows[1]["decision"] = "adopt"
    (out / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    entry = regrade(t.usecase, out)["entries"][1]
    assert entry["decision"] == "screened" and entry["agrees"] is False
    (out / "candidates/000/val/episodes.jsonl").unlink()
    with pytest.raises(ValueError, match="validation|val"):
        regrade(t.usecase, out)


def test_interrupted_baseline_reuses_any_completed_split(tmp_path, monkeypatch):
    import harness_loop.loop as loop

    out = tmp_path / "run"
    t = target(tmp_path)
    score = loop._score

    def interrupted(*args, **kwargs):
        if args[3] == "val":
            raise KeyboardInterrupt
        return score(*args, **kwargs)

    monkeypatch.setattr(loop, "_score", interrupted)
    with pytest.raises(KeyboardInterrupt):
        campaign(t, scripted([]), out)
    dev = out / "candidates/000/dev/episodes.jsonl"
    saved_time = dev.stat().st_mtime_ns
    monkeypatch.setattr(loop, "_score", score)
    campaign(t, scripted([]), out)
    assert dev.stat().st_mtime_ns == saved_time


def test_silent_command_failure_pauses_before_test(tmp_path):
    import sys

    from harness_loop import command

    out = tmp_path / "run"
    failed = command([sys.executable, "-c", "raise SystemExit(3)"])
    r = campaign(target(tmp_path), failed, out, patience=1)
    assert "3" in r["stopped"] and "the improver failed" in r["stopped"]
    assert not (out / "test").exists()
    assert len(read_ledger(out)) == 1
    assert r["spent"]["improver_unknown"] == 1


def test_campaign_budget_counts_noise_and_final_test(tmp_path):
    out = tmp_path / "run"
    n = {"dev": 1, "val": 1, "test": 1}
    # 14 seed episodes and eight noise episodes at $0.001 each exceed the search budget.
    r = campaign(
        target(tmp_path), scripted([write(REVERSE, "reverse")]), out, trials=n, max_usd=0.020
    )
    assert "spent" in r["stopped"] and r["final"] == "000"
    assert r["spent"]["eval_episodes"] == 30
    assert r["spent"]["eval_usd"] == pytest.approx(0.030)


def test_resume_refuses_changed_screen_improver_and_seed(tmp_path):
    from harness_loop import command

    t, out = target(tmp_path), tmp_path / "run"
    campaign(t, scripted([]), out, test=False)
    with pytest.raises(ValueError, match="screen"):
        campaign(t, scripted([]), out, screen=False)
    with pytest.raises(ValueError, match="improver"):
        campaign(t, command(["another"]), out)
    (t.seed / "harness.py").write_text(REVERSE)
    with pytest.raises(ValueError, match="seed"):
        campaign(t, scripted([]), out)


def test_coverage_and_provenance_are_checked_before_regrading(tmp_path):
    t, out = target(tmp_path), tmp_path / "run"
    campaign(t, scripted([]), out)
    manifest = out / "candidates/000/dev/manifest.json"
    old = manifest.read_text()
    data = json.loads(old)
    data["frozen"]["model"] = "another"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="frozen"):
        regrade(t.usecase, out)
    manifest.write_text(old)
    episodes = out / "test/000/episodes.jsonl"
    lines = episodes.read_text().splitlines()
    lines[0] = lines[-1]
    episodes.write_text("\n".join(lines))
    with pytest.raises(ValueError, match="coverage"):
        regrade(t.usecase, out)


def test_interruptions_preserve_proposal_and_test_selection(monkeypatch, tmp_path):
    import harness_loop.loop as loop

    t, out = target(tmp_path), tmp_path / "run"
    score = loop._score
    calls = []

    def one_proposal(ws):
        calls.append("proposal")
        write(REVERSE, "")(ws / "harness")
        return Proposal(cost_usd=0.50)

    def interrupt_proposal(target, out, cid, split, *args, **kwargs):
        if cid == "001" and split == "val":
            raise KeyboardInterrupt
        return score(target, out, cid, split, *args, **kwargs)

    monkeypatch.setattr(loop, "_score", interrupt_proposal)
    with pytest.raises(KeyboardInterrupt):
        campaign(t, one_proposal, out, max_candidates=1)

    def interrupt_test(target, out, cid, split, *args, **kwargs):
        if cid == "001" and split == "test":
            raise KeyboardInterrupt
        return score(target, out, cid, split, *args, **kwargs)

    monkeypatch.setattr(loop, "_score", interrupt_test)
    with pytest.raises(KeyboardInterrupt):
        campaign(t, one_proposal, out, max_candidates=1)
    assert (out / "test/000/episodes.jsonl").exists()
    monkeypatch.setattr(loop, "_score", score)
    result = campaign(t, one_proposal, out, max_candidates=2)
    assert result["final"] == "001" and result["spent"]["improver_usd"] == 0.50
    assert calls == ["proposal"]


def test_replay_marks_unscored_candidates_as_recorded_only(tmp_path):
    t, out = target(tmp_path, validate=lambda _: ["invalid"]), tmp_path / "run"
    campaign(t, scripted([write(REVERSE, "reverse")]), out)
    entry = regrade(t.usecase, out)["entries"][1]
    assert entry["decision"] == "invalid" and entry["agrees"] is None
    assert "invalid (recorded only)" in report(t.usecase, out)


def test_replay_does_not_promote_a_change_from_a_different_parent(tmp_path):
    t, out = target(tmp_path), tmp_path / "run"
    first = "def reply(w):\n    return w if w == 'table' else w[::-1]\n"
    second = f"def reply(w):\n    return w[::-1] if w in {WORDS['dev']!r} else '!' + w[::-1]\n"
    campaign(
        t, scripted([write(first, "keep table"), write(second, "prefix")]), out, max_candidates=2
    )
    revised = usecase()
    revised.tasks = [
        Task(task.id, task.input, (says(f"^!{task.input[::-1]}$"),), split=task.split)
        if task.split == "val"
        else task
        for task in revised.tasks
    ]
    result = regrade(revised, out)
    assert result["entries"][2]["decision"] == "adopt"
    assert result["entries"][2]["off_path"] and result["final"] == "000"
    text = report(revised, out)
    assert "adopted 1. Regrading supports 0" in text
    assert (out / "trajectory.svg").read_text().count('class="kept"') == 1


def test_openai_agent_uses_workspace_tools_computes_cost_and_denies_escapes(tmp_path, monkeypatch):
    import io
    import urllib.request

    from harness_loop import openai_agent

    ws = tmp_path / "ws"
    (ws / "harness").mkdir(parents=True)
    (ws / "TASK.md").write_text("# Task\nReverse the word.\n")
    (ws / "harness" / "harness.py").write_text(SEED)
    (tmp_path / "secret.txt").write_text("do-not-read")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    calls = []
    scripted_replies = [
        {
            "output": [
                {
                    "type": "function_call",
                    "call_id": "t1",
                    "name": "read_file",
                    "arguments": json.dumps({"path": "TASK.md"}),
                },
                {
                    "type": "function_call",
                    "call_id": "t2",
                    "name": "read_file",
                    "arguments": json.dumps({"path": "../secret.txt"}),
                },
                {
                    "type": "function_call",
                    "call_id": "t3",
                    "name": "read_file",
                    "arguments": json.dumps({"path": "/etc/hosts"}),
                },
            ],
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 400, "cache_write_tokens": 0},
            },
        },
        {
            "output": [
                {
                    "type": "function_call",
                    "call_id": "t4",
                    "name": "edit_file",
                    "arguments": json.dumps(
                        {
                            "path": "harness/harness.py",
                            "old_text": "    return word",
                            "new_text": "    return word[::-1]",
                        }
                    ),
                },
                {
                    "type": "function_call",
                    "call_id": "t5",
                    "name": "write_file",
                    "arguments": json.dumps({"path": "NOTE.md", "content": "Reversed the string."}),
                },
            ],
            "usage": {
                "input_tokens": 2000,
                "output_tokens": 200,
                "input_tokens_details": {"cached_tokens": 1000, "cache_write_tokens": 0},
            },
        },
        {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Done."}]}],
            "usage": {
                "input_tokens": 500,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            },
        },
    ]

    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        calls.append(body)
        reply = scripted_replies[len(calls) - 1]

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.close()

        return Resp(json.dumps(reply).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    prop = openai_agent(model="gpt-6.2-sol", reasoning_effort="medium")(ws)
    assert prop.error is None
    assert prop.model == "gpt-6.2-sol"
    assert (ws / "harness" / "harness.py").read_text() == REVERSE
    assert (ws / "NOTE.md").read_text() == "Reversed the string."
    # Turn 1: 600*2e-6 + 400*1e-7 + 100*1e-5 = 0.00224
    # Turn 2: 1000*2e-6 + 1000*1e-7 + 200*1e-5 = 0.00410
    # Turn 3: 500*2e-6 + 20*1e-5 = 0.00120 => total = 0.00754
    assert prop.cost_usd == pytest.approx(0.00754)
    assert len(prop.denied) == 2
    assert "read_file" in prop.denied[0] and "../secret.txt" in prop.denied[0]
    assert "<outside the workspace>/etc/hosts" in prop.denied[1]
    assert "do-not-read" not in json.dumps(calls[-1])

    # Unknown model leaves cost_usd as None instead of 0.0
    calls.clear()
    scripted_replies[:] = [
        {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Done."}]}],
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }
    ]
    unknown = openai_agent(model="unknown-custom-model")(ws)
    assert unknown.error is None and unknown.cost_usd is None


# -- objectives, another start and the frontier ----------------------------------------------


def priced(code: str, cost: float, latency: float = 0.1) -> str:
    return code + f"COST = {cost}\nLATENCY = {latency}\n"


def start_at(tmp_path: Path, code: str) -> Path:
    start = tmp_path / "start"
    start.mkdir(exist_ok=True)
    (start / "harness.py").write_text(code)
    return start


def test_a_cost_campaign_adopts_a_cheaper_harness_and_drops_one_that_loses_success(tmp_path):
    t = target(tmp_path)
    t.usecase.guardrails = {"latency_p95": ("<=", 1.0)}
    start = start_at(tmp_path, priced(REVERSE, 0.002))
    steps = [
        write(priced(SEED, 0.0005), "cheaper, but echoes"),
        write(priced(REVERSE, 0.002) + "# same cost\n", "a comment"),
        write(priced(REVERSE, 0.001), "cheaper"),
    ]
    out, n = tmp_path / "run", {"dev": 1, "val": 1, "test": 1}
    kw = {"trials": n, "objective": "cost_per_task", "seed": start, "patience": 5}
    result = campaign(t, scripted(steps), out, **kw, max_candidates=3)
    rows = read_ledger(out)
    assert [r["decision"] for r in rows] == ["seed", "screened", "screened", "adopt"]
    assert rows[1]["reasons"][0].startswith("development success 0.33 is below the base's 1.00")
    assert rows[2]["reasons"][0].startswith("development cost_per_task 0.002 is not below")
    assert rows[3]["reasons"][0].startswith("cost_per_task is lower")
    assert rows[3]["reasons"][1].startswith("success holds")
    assert rows[3]["dev"]["cost_per_task"] == pytest.approx(0.001)
    # No development task fails from the start: only the success objective stops on that.
    assert result["stopped"] == "reached 3 candidates" and result["final"] == "003"
    assert result["test"]["decision"] == "adopt"
    assert json.loads((out / "noise.json").read_text())["decision"] == "inconclusive"
    task = (out / "candidates" / "001" / "seen" / "TASK.md").read_text()
    assert "This campaign lowers `cost_per_task`. Success must not fall" in task
    assert "`latency_p95` may change by <= +1" in task and "should lower `cost_per_task`" in task
    r = regrade(t.usecase, out)
    assert all(e["agrees"] for e in r["entries"][1:])
    assert "objective `cost_per_task`" in report(t.usecase, out)
    # A cheaper harness that loses success is rejected on validation when nothing screens.
    steps = [write(priced(SEED, 0.0005), "cheaper, but echoes")]
    campaign(t, scripted(steps), tmp_path / "open", **kw, screen=False, max_candidates=1)
    row = read_ledger(tmp_path / "open")[1]
    assert row["decision"] == "reject" and row["reasons"][0].startswith("success is lower")
    with pytest.raises(ValueError, match="different objective"):
        campaign(t, scripted([]), out, trials=n, seed=start)
    with pytest.raises(ValueError, match="objective 'speed'"):
        campaign(t, scripted([]), tmp_path / "bad", objective="speed")


def test_a_latency_campaign_runs_the_base_again_next_to_each_candidate(tmp_path):
    t = target(tmp_path)
    start = start_at(tmp_path, priced(REVERSE, 0.001, latency=0.5))
    out, n = tmp_path / "run", {"dev": 1, "val": 1, "test": 1}
    steps = [write(priced(REVERSE, 0.001, latency=0.2), "faster")]
    campaign(t, scripted(steps), out, trials=n, objective="latency_p95", seed=start)
    row = read_ledger(out)[1]
    assert row["decision"] == "adopt" and row["reasons"][0].startswith("latency_p95 is lower")
    again = out / "candidates" / "001" / "val-base"
    assert json.loads((again / "manifest.json").read_text())["harnesses"] == ["000"]
    assert row["eval"]["episodes"] == 6 + 8 + 8  # dev, val and the base's val again
    assert regrade(t.usecase, out)["entries"][1]["agrees"]


def test_a_campaign_can_start_from_another_harness(tmp_path):
    t, out = target(tmp_path), tmp_path / "run"
    start = start_at(tmp_path, REVERSE)
    campaign(t, scripted([]), out, seed=start, test=False)
    assert (out / "candidates" / "000" / "harness" / "harness.py").read_text() == REVERSE
    config = json.loads((out / "campaign.json").read_text())
    assert config["seed"] == read_ledger(out)[0]["tree"] and config["seed_dir"].endswith("start")
    assert config["objective"] == "success"
    with pytest.raises(ValueError, match="different seed"):
        campaign(t, scripted([]), out, test=False)


def test_the_run_command_passes_objective_seed_and_frontier(tmp_path, monkeypatch):
    import harness_loop.cli as cli

    got = {}
    monkeypatch.setattr(cli, "_target", lambda ref: target(tmp_path))
    monkeypatch.setattr(
        cli, "campaign", lambda *a, **kw: got.update(kw) or {"stopped": "", "final": ""}
    )
    monkeypatch.setattr(cli, "report", lambda usecase, out: "")
    argv = ["run", "x", str(tmp_path / "run"), "--improver", "true", "--seed", str(tmp_path)]
    main([*argv, "--objective", "cost_per_task", "--frontier"])
    assert got["objective"] == "cost_per_task" and got["seed"] == tmp_path and got["frontier"]
    main(argv)
    assert got["objective"] == "success" and got["frontier"] is False


def test_the_frontier_keeps_every_harness_no_other_beats_on_all_three_metrics():
    from harness_evals import pareto

    from harness_loop.loop import non_dominated

    def s(success, cost, latency):
        return {"success": success, "cost_per_task": cost, "latency_p95": latency}

    sums = {
        "a": s(0.9, 2.0, 3.0),
        "b": s(0.9, 1.0, 4.0),
        "c": s(0.8, 3.0, 1.0),  # beaten on success and cost by a, but the fastest
        "d": s(0.8, 3.0, 2.0),  # c is as good on all three and faster
        "e": s(0.9, 2.0, 3.0),  # the same point as a: neither beats the other
        "f": {**s(1.0, 0.5, 1.0), "unknown_cost": 1},  # cost unknown: left out
    }
    assert non_dominated(sums) == ["a", "b", "c", "e"]
    assert "c" not in pareto(sums, "cost_per_task", "success")  # two metrics drop c


def test_a_campaign_scores_its_frontier_on_the_test_tasks(tmp_path):
    t = target(tmp_path)
    t.usecase.gates = {"latency_p95": ("<=", 1.0)}
    start = start_at(tmp_path, priced(REVERSE, 0.002, latency=0.2))
    steps = [
        write(priced(REVERSE, 0.001, latency=0.3), "cheaper, a little slower"),
        write(priced(REVERSE, 0.0005, latency=2.0), "cheapest, past the latency bar"),
        write(priced(REVERSE, 0.001, latency=0.4), "as cheap, slower"),
        write(priced(SEED, 0.0001, latency=0.1), "cheap and fast, but echoes"),
    ]
    out, n = tmp_path / "run", {"dev": 1, "val": 1, "test": 1}
    kw = {"trials": n, "objective": "cost_per_task", "seed": start, "screen": False}
    result = campaign(t, scripted(steps), out, **kw, patience=5, frontier=True)
    rows = read_ledger(out)
    assert [r["decision"] for r in rows] == [
        "seed",
        "adopt",
        "reject",
        "inconclusive",
        "reject",
    ]
    assert [m["id"] for m in result["frontier"]] == ["000", "001", "004"]
    assert result["frontier"][2]["test"]["success"] == 0.25
    assert sorted(p.name for p in (out / "test").iterdir()) == ["000", "001", "004"]
    saved = json.loads((out / "result.json").read_text())
    assert [m["id"] for m in saved["frontier"]] == ["000", "001", "004"]
    text = report(t.usecase, out)
    assert "## The frontier" in text and "| 004 | 0.25 | $0.00010 | 0.10 | unknown |" in text
    assert (out / "frontier-cost.svg").read_text().startswith("<svg")
    assert (out / "frontier-latency.svg").read_text().startswith("<svg")
    # Without the flag the test tasks see the start and the final harness only.
    campaign(t, scripted(steps), tmp_path / "plain", **kw, patience=5)
    assert sorted(p.name for p in (tmp_path / "plain" / "test").iterdir()) == ["000", "001"]
    assert "frontier" not in json.loads((tmp_path / "plain" / "result.json").read_text())


def test_the_frontier_command_reads_the_saved_sql_campaigns(tmp_path, capsys):
    campaigns = Path(__file__).parents[1] / "examples" / "sql_desk" / "campaigns"
    folders = [str(campaigns / c) for c in ("run-1", "run-2", "no-feedback-1", "no-feedback-2")]
    main(["frontier", "examples.sql_desk.target:TARGET", *folders, "--out", str(tmp_path)])
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(" | ")[0] for line in lines[2:]] == [
        "| run-1/000",
        "| run-1/002",
        "| run-2/001",
    ]
    assert all(line.endswith("| yes |") for line in lines[2:])
    assert (tmp_path / "frontier-cost.svg").exists() and (
        tmp_path / "frontier-latency.svg"
    ).exists()
    with pytest.raises(SystemExit, match="not comparable|differs"):
        other = tmp_path / "other"
        import shutil

        shutil.copytree(campaigns / "run-2", other)
        manifest = other / "test" / "001" / "manifest.json"
        data = json.loads(manifest.read_text())
        data["frozen"]["model"] = "another"
        manifest.write_text(json.dumps(data))
        main(["frontier", "examples.sql_desk.target:TARGET", folders[0], str(other)])
