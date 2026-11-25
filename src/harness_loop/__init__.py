"""Improve an agent harness in a closed loop with the model held fixed."""

__version__ = "0.3.0"

from harness_loop.improvers import claude_code, command, openai_agent, scripted  # noqa: E402
from harness_loop.loop import (  # noqa: E402
    Finished,
    Proposal,
    Target,
    campaign,
    files,
    non_dominated,
    patch,
    read_ledger,
    scrub,
)
from harness_loop.report import regrade, report, trajectory_svg  # noqa: E402

__all__ = [
    "Finished",
    "Proposal",
    "Target",
    "campaign",
    "claude_code",
    "command",
    "files",
    "non_dominated",
    "openai_agent",
    "patch",
    "read_ledger",
    "regrade",
    "report",
    "scripted",
    "scrub",
    "trajectory_svg",
]
