"""Improvers: what edits the harness in one step of the loop.

An improver is a function ``(workspace) -> Proposal``. It changes files under
``<workspace>/harness`` and may write ``<workspace>/NOTE.md``. The loop copies the
harness back out and ignores every other change.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from harness_loop.loop import Finished, Improver, Proposal, scrub

PROMPT = "Read TASK.md in this directory and do what it says."

# Official OpenAI API token rates (2026-11): (uncached_in, cached_in, cache_write, output).
OPENAI_PRICES: dict[str, tuple[float, float, float, float]] = {
    "gpt-6.2-sol": (2e-6, 1e-7, 2.5e-6, 1e-5),
    "gpt-6.1-terra": (1e-6, 5e-8, 1.25e-6, 5e-6),
}

_SKIP_PARTS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache"}
_SKIP_NAMES = {".DS_Store"}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".db"}
_MAX_READ_CHARS = 30_000
_MAX_GLOB_PATHS = 200
_MAX_GREP_MATCHES = 100

_OPENAI_SYSTEM = """\
You are an automated harness engineering improver working inside a temporary workspace.

Read `TASK.md` in the workspace root first, then inspect `harness/`, `feedback/` (if
present), `history.md`, and `reference/` (if present). Use only the provided file tools.
Make one focused edit strictly inside `harness/` that addresses the failures without
hard-coding or copying development task inputs, write `NOTE.md` in the workspace root
explaining what you changed and why, then stop with a concise plain-text summary."""

_OPENAI_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a text file inside the workspace with 1-based line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path inside workspace."},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "edit_file",
        "description": "Replace one exact text occurrence inside a workspace file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "Write full contents to a workspace file, creating parent dirs.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "glob_files",
        "description": "List relative file paths inside the workspace matching a glob pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Glob pattern relative to workspace, e.g. '**/*' or 'harness/*.py'."
                    ),
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "grep_files",
        "description": "Search workspace text files using a Python regex pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
]

# Claude Code's restricted mode removes the tools that run commands and confines the
# file tools to the working directory, so the improver can read and edit the workspace
# and nothing else. The loop keeps the campaign directory outside it.
CLAUDE_FLAGS = (
    "--restricted",
    "--strict-mcp-config",
    "--permission-mode",
    "acceptEdits",
    "--tools",
    "Read,Edit,Write,Glob,Grep",
    "--output-format",
    "json",
    "--no-session-persistence",
)


def _openai_key() -> str | None:
    if key := os.environ.get("OPENAI_API_KEY"):
        return key
    cwd = Path.cwd()
    for candidate in (cwd / ".env.local", cwd / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, v = stripped.partition("=")
            if k.strip() == "OPENAI_API_KEY" and (val := v.strip().strip("'\"")):
                return val
    return None


def _resolve_in_workspace(root: Path, raw: str) -> Path | None:
    if not isinstance(raw, str):
        return None
    p = Path(raw)
    target = (p if p.is_absolute() else root / p).resolve()
    return target if target.is_relative_to(root) else None


def _is_skipped(rel: Path) -> bool:
    return (
        any(part in _SKIP_PARTS for part in rel.parts)
        or rel.name in _SKIP_NAMES
        or rel.suffix in _SKIP_SUFFIXES
    )


def _exec_tool(name: str, args: dict[str, Any], root: Path, denied: list[str]) -> str:
    def deny() -> str:
        denied.append(f"{name} {json.dumps(_local(args, root))}")
        return f"Access denied: path outside the workspace for {name}."

    if name == "read_file":
        target = _resolve_in_workspace(root, args.get("path", ""))
        if target is None:
            return deny()
        if not target.exists():
            return f"Error: file not found: {args.get('path')}"
        if not target.is_file():
            return f"Error: not a file: {args.get('path')}"
        start = int(args.get("start_line") or 1)
        end = int(args.get("end_line") or 400)
        if start < 1 or end < start:
            return "Error: start_line must be >= 1 and end_line >= start_line."
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = lines[start - 1 : end]
        numbered = "\n".join(f"{start + i}: {line}" for i, line in enumerate(selected))
        if len(numbered) > _MAX_READ_CHARS:
            numbered = numbered[:_MAX_READ_CHARS] + "\n... [truncated at 30,000 chars]"
        if end < len(lines):
            numbered += f"\n... [lines {start}-{end} of {len(lines)} shown]"
        return numbered or "(empty file)"

    if name == "edit_file":
        target = _resolve_in_workspace(root, args.get("path", ""))
        if target is None:
            return deny()
        if not target.is_file():
            return f"Error: file not found: {args.get('path')}"
        old_text = args.get("old_text")
        new_text = args.get("new_text")
        if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
            return "Error: old_text must be a non-empty string and new_text must be a string."
        content = target.read_text(encoding="utf-8", errors="replace")
        count = content.count(old_text)
        if count == 0:
            return f"Error: old_text not found in {args.get('path')}."
        if count > 1:
            return f"Error: old_text appears {count} times in {args.get('path')}; be more specific."
        target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {target.relative_to(root).as_posix()}."

    if name == "write_file":
        target = _resolve_in_workspace(root, args.get("path", ""))
        if target is None:
            return deny()
        content = args.get("content")
        if not isinstance(content, str):
            return "Error: content must be a string."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {target.relative_to(root).as_posix()} ({len(content)} chars)."

    if name == "glob_files":
        pattern = args.get("pattern", "")
        if not isinstance(pattern, str) or not pattern:
            return "Error: pattern must be a non-empty string."
        pat_path = Path(pattern)
        if pat_path.is_absolute() or ".." in pat_path.parts:
            return deny()
        norm_pattern = pat_path.as_posix()
        matches: list[str] = []
        for p in sorted(root.rglob("*")):
            resolved = p.resolve()
            if not resolved.is_relative_to(root) or not p.is_file():
                continue
            rel = resolved.relative_to(root)
            if _is_skipped(rel):
                continue
            rel_s = rel.as_posix()
            if fnmatch.fnmatch(rel_s, norm_pattern) or (
                norm_pattern.startswith("**/") and fnmatch.fnmatch(rel_s, norm_pattern[3:])
            ):
                matches.append(rel_s)
                if len(matches) >= _MAX_GLOB_PATHS:
                    break
        if not matches:
            return "(no matches)"
        suffix = (
            f"\n... [capped at {_MAX_GLOB_PATHS} paths]" if len(matches) >= _MAX_GLOB_PATHS else ""
        )
        return "\n".join(matches) + suffix

    if name == "grep_files":
        raw_path = args.get("path") or "."
        target = _resolve_in_workspace(root, raw_path)
        if target is None:
            return deny()
        if not target.exists():
            return f"Error: path not found: {raw_path}"
        pattern = args.get("pattern", "")
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return f"Error: invalid regex: {exc}"
        candidates = (
            [target]
            if target.is_file()
            else sorted(
                p for p in target.rglob("*") if p.resolve().is_relative_to(root) and p.is_file()
            )
        )
        hits: list[str] = []
        for p in candidates:
            rel = p.resolve().relative_to(root)
            if _is_skipped(rel):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for idx, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel.as_posix()}:{idx}:{line[:240]}")
                    if len(hits) >= _MAX_GREP_MATCHES:
                        break
            if len(hits) >= _MAX_GREP_MATCHES:
                break
        if not hits:
            return "(no matches)"
        suffix = (
            f"\n... [capped at {_MAX_GREP_MATCHES} matches]"
            if len(hits) >= _MAX_GREP_MATCHES
            else ""
        )
        return "\n".join(hits) + suffix

    denied.append(f"{name} {json.dumps(_local(args, root))}")
    return f"Error: tool {name!r} is not allowed."


def _openai_call(
    endpoint: str, api_key: str, body: dict[str, Any], timeout_s: float
) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    for attempt in range(4):
        req = urllib.request.Request(endpoint, payload, headers)
        try:
            with urllib.request.urlopen(req, timeout=max(1.0, min(120.0, timeout_s))) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(float(2**attempt))
                continue
            detail = ""
            try:
                err_body = json.loads(exc.read().decode("utf-8", errors="replace"))
                detail = str((err_body.get("error") or {}).get("message") or "")[:200]
            except Exception:
                pass
            raise RuntimeError(
                f"HTTP {exc.code} from OpenAI API{f': {detail}' if detail else ''}"
            ) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                time.sleep(float(2**attempt))
                continue
            raise RuntimeError(f"OpenAI API connection failed: {exc}") from None
    raise RuntimeError("OpenAI API failed after retries")  # pragma: no cover


def _usage_cost(model: str, usage: dict[str, Any] | None) -> float | None:
    rates = OPENAI_PRICES.get(model)
    if rates is None or not usage:
        return None
    inp = usage.get("input_tokens") if "input_tokens" in usage else usage.get("prompt_tokens")
    out = usage.get("output_tokens") if "output_tokens" in usage else usage.get("completion_tokens")
    if inp is None or out is None:
        return None
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens", 0) or 0
    cache_write = details.get("cache_write_tokens", 0) or 0
    uncached = max(int(inp) - int(cached) - int(cache_write), 0)
    return (
        uncached * rates[0]
        + int(cached) * rates[1]
        + int(cache_write) * rates[2]
        + int(out) * rates[3]
    )


def openai_agent(
    model: str = "gpt-6.2-sol",
    *,
    url: str = "https://api.openai.com/v1",
    reasoning_effort: str = "medium",
    budget_usd: float = 1.5,
    max_steps: int = 30,
    timeout: float = 600.0,
) -> Improver:
    """Built-in workspace-confined file-tool improver using the OpenAI Responses API
    (stdlib ``urllib`` only). Refuses and logs any path access outside the workspace."""
    endpoint = url.rstrip("/") + "/responses"

    def propose(workspace: Path) -> Proposal:
        began = time.perf_counter()
        deadline = began + timeout
        api_key = _openai_key()
        if not api_key:
            return Proposal(
                seconds=time.perf_counter() - began,
                model=model,
                error="OPENAI_API_KEY is not set in environment or .env.local/.env",
            )
        root = workspace.resolve()
        denied: list[str] = []
        items: list[dict[str, Any]] = [{"role": "user", "content": PROMPT}]
        total_cost = 0.0
        cost_known = model in OPENAI_PRICES

        for _step in range(max_steps):
            remaining = deadline - time.perf_counter()
            if remaining <= 0 or (cost_known and total_cost >= budget_usd):
                break
            body: dict[str, Any] = {
                "model": model,
                "instructions": _OPENAI_SYSTEM,
                "input": items,
                "tools": _OPENAI_TOOLS,
                "tool_choice": "auto",
                "max_output_tokens": 16384,
                "store": False,
                "include": ["reasoning.encrypted_content"],
            }
            if reasoning_effort:
                body["reasoning"] = {"effort": reasoning_effort}
            try:
                reply = _openai_call(endpoint, api_key, body, remaining)
            except Exception as exc:  # noqa: BLE001
                return Proposal(
                    cost_usd=round(total_cost, 6) if (cost_known and total_cost > 0) else None,
                    seconds=time.perf_counter() - began,
                    model=model,
                    denied=denied,
                    error=scrub(str(exc))[-500:],
                )
            step_cost = _usage_cost(model, reply.get("usage"))
            if step_cost is None:
                cost_known = False
            else:
                total_cost += step_cost

            output = reply.get("output") or []
            if not output:
                return Proposal(
                    cost_usd=round(total_cost, 6) if cost_known else None,
                    seconds=time.perf_counter() - began,
                    model=model,
                    denied=denied,
                    error="OpenAI API returned no output items",
                )
            items.extend(output)
            tool_calls = [item for item in output if item.get("type") == "function_call"]
            if not tool_calls:
                break

            for tc in tool_calls:
                tname = tc.get("name", "")
                raw_args = tc.get("arguments") or "{}"
                try:
                    parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    if not isinstance(parsed, dict):
                        raise TypeError("tool arguments must be a JSON object")
                except (json.JSONDecodeError, TypeError) as exc:
                    result = f"Error parsing tool arguments JSON: {exc}"
                else:
                    result = _exec_tool(tname, parsed, root, denied)
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": tc.get("call_id", ""),
                        "output": result,
                    }
                )

        return Proposal(
            cost_usd=round(total_cost, 6) if cost_known else None,
            seconds=time.perf_counter() - began,
            model=model,
            denied=denied,
        )

    propose.describe = {
        "kind": "openai-agent",
        "model": model,
        "url": url,
        "reasoning_effort": reasoning_effort,
        "tools": ["read_file", "edit_file", "write_file", "glob_files", "grep_files"],
    }
    return propose


def claude_code(
    model: str = "sonnet", *, budget_usd: float = 2.0, timeout: float = 1200.0
) -> Improver:
    """Claude Code, headless and restricted, as the improver. ``budget_usd`` caps one
    proposal; the cost it reports is what the calls cost at list price."""
    argv = ["claude", "-p", PROMPT, *CLAUDE_FLAGS, "--model", model]
    argv += ["--max-budget-usd", str(budget_usd)]

    def propose(workspace: Path) -> Proposal:
        began = time.perf_counter()
        r = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, timeout=timeout)
        seconds = time.perf_counter() - began
        try:
            reply = json.loads(r.stdout)
        except json.JSONDecodeError:
            detail = scrub((r.stderr or r.stdout).strip())[-500:]
            return Proposal(
                seconds=seconds, error=detail or f"no JSON response (exit {r.returncode})"
            )
        return Proposal(
            cost_usd=reply.get("total_cost_usd"),
            seconds=seconds,
            model=", ".join(reply.get("modelUsage") or {}) or model,
            denied=[
                f"{d.get('tool_name')} {json.dumps(_local(d.get('tool_input'), workspace))}"
                for d in reply.get("permission_denials") or []
            ],
            error=(
                scrub(str(reply.get("result") or r.stderr).strip())[-500:]
                or f"Claude Code failed (exit {r.returncode})"
            )
            if r.returncode or reply.get("is_error")
            else None,
        )

    propose.describe = {"kind": "claude-code", "argv": argv, "version": _version("claude")}
    return propose


def command(argv: Sequence[str], *, timeout: float = 1200.0) -> Improver:
    """Any command-line agent: it runs in the workspace and edits ``harness/`` there.
    Its cost is unknown to the loop, and so is what it can read: sandbox it yourself."""

    def propose(workspace: Path) -> Proposal:
        r = subprocess.run(
            list(argv), cwd=workspace, capture_output=True, text=True, timeout=timeout
        )
        return Proposal(
            error=(scrub(r.stderr.strip())[-500:] or f"command exited with {r.returncode}")
            if r.returncode
            else None
        )

    propose.describe = {"kind": "command", "argv": list(argv)}
    return propose


def scripted(steps: Iterable[Callable[[Path], str]]) -> Improver:
    """Prepared changes, one per step: each function edits the harness directory it is
    given and returns its note. For tests, replays and a hand-written baseline."""
    queue = iter(steps)

    def propose(workspace: Path) -> Proposal:
        step = next(queue, None)
        if step is None:
            raise Finished
        return Proposal(note=step(workspace / "harness"), cost_usd=0.0, model="scripted")

    propose.describe = {"kind": "scripted"}
    return propose


def _local(value: object, workspace: Path) -> object:
    """A refused tool call without the machine's directory names: a path inside the
    workspace becomes relative, and one outside keeps its last two parts."""
    if isinstance(value, dict):
        return {k: _local(v, workspace) for k, v in sorted(value.items())}
    if isinstance(value, str) and value.startswith("/"):
        path = Path(value)
        if path.is_relative_to(workspace):
            return str(path.relative_to(workspace))
        return "<outside the workspace>/" + "/".join(path.parts[-2:])
    return value


def _version(tool: str) -> str:
    try:
        return subprocess.run([tool, "--version"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return "not found"
