"""Run a harness directory on a list of questions, in a process of its own.

    python -m examples.sql_desk.runner <harness dir> <tasks.json> <out.json> <trial>

It writes what the harness returned and what the environment recorded. It does not grade:
the evaluator runs the returned query itself, in its own process.
"""

from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from examples.sql_desk.shop import Db, Model, build

URL = os.environ.get("SQL_DESK_URL", "https://api.openai.com/v1")
MODEL = os.environ.get("SQL_DESK_MODEL", "gpt-6.2-sol")
REASONING_EFFORT = os.environ.get("SQL_DESK_REASONING_EFFORT", "low")
CONCURRENCY = int(os.environ.get("SQL_DESK_CONCURRENCY", "6"))
SECONDS = 90  # per question
REPO = Path(__file__).resolve().parents[2]


def _api_key() -> str:
    if key := os.environ.get("OPENAI_API_KEY"):
        return key
    for env_file in (REPO / ".env.local", REPO / ".env"):
        if not env_file.exists():
            continue
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == "OPENAI_API_KEY" and (val := v.strip().strip("'\"")):
                return val
    if "api.openai.com" in URL:
        raise SystemExit("Set OPENAI_API_KEY in the environment before running sql_desk")
    return ""


def main(harness: str, tasks: str, out: str, trial: str) -> None:
    api_key = _api_key()
    sys.path.insert(0, harness)  # the harness may be more than one file
    spec = importlib.util.spec_from_file_location("desk", Path(harness) / "desk.py")
    desk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(desk)
    task_list = json.loads(Path(tasks).read_text())
    seed = int(trial)

    def run_one(task: dict) -> dict:
        db = Db(shop)
        model = Model(
            URL,
            MODEL,
            seed=seed,
            api_key=api_key,
            reasoning_effort=REASONING_EFFORT,
            deadline=time.perf_counter() + SECONDS,
        )
        sql, error, began = None, None, time.perf_counter()
        try:
            sql = desk.answer(task["question"], db, model)
        except Exception as exc:  # noqa: BLE001 - any failure of the harness is recorded
            error = repr(exc).replace(str(Path.home()), "~")[:300]
        finally:
            db.close()
        return {
            "id": task["id"],
            "sql": sql if isinstance(sql, str) else None,
            "error": error,
            "log": db.log,
            "latency_s": time.perf_counter() - began,
            "calls": model.calls,
            "input_tokens": model.input_tokens,
            "cached_input_tokens": model.cached_input_tokens,
            "cache_write_tokens": model.cache_write_tokens,
            "output_tokens": model.output_tokens,
            "reasoning_tokens": model.reasoning_tokens,
        }

    with tempfile.TemporaryDirectory() as tmp:
        shop = build(Path(tmp) / "shop.sqlite")
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, CONCURRENCY)) as pool:
            results = list(pool.map(run_one, task_list))
    Path(out).write_text(json.dumps(results))


if __name__ == "__main__":
    main(*sys.argv[1:5])
