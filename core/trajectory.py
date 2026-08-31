"""Structured run log.

This is submission deliverable #4, not a debugging aid. It is written as the
agent runs so trajectories never have to be reconstructed afterwards, and it
is the evidence every changelog claim points back to.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import RUNS_DIR


@dataclass
class RunStats:
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    cost_usd: float = 0.0
    cache_hits: int = 0
    llm_calls: int = 0
    wall_seconds: float = 0.0


class Trajectory:
    def __init__(self, run_id: str | None = None, meta: dict | None = None):
        RUNS_DIR.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # Every invocation gets its own file. Records are appended as the run
        # proceeds, so a deterministic name would silently splice a re-run onto
        # the previous one -- and these files are a submission deliverable, so
        # the run to ship should be chosen rather than being whichever ran last.
        self.run_id = f"{run_id}_{stamp}" if run_id else stamp
        self.path = RUNS_DIR / f"{self.run_id}.jsonl"
        if self.path.exists():                      # same second, same case
            self.path = RUNS_DIR / f"{self.run_id}_{os.getpid()}.jsonl"
        self.stats = RunStats()
        self._t0 = time.time()
        self.record("run_start", meta or {})

    def record(self, kind: str, data: dict[str, Any]) -> None:
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "elapsed": round(time.time() - self._t0, 3),
            "kind": kind,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")

    def finish(self, outcome: str, summary: str = "") -> RunStats:
        self.stats.wall_seconds = round(time.time() - self._t0, 2)
        self.record("run_end", {"outcome": outcome, "summary": summary,
                                "stats": asdict(self.stats)})
        return self.stats

    def render(self, *, full: bool = False) -> str:
        """Human-readable replay — what goes in the submission, not raw JSONL.

        The renderer lives in core.replay so that the same code serves both
        this method and `python -m core.replay <file>`; a trajectory written by
        one run is usually read back long after that run's object is gone.
        """
        from .replay import render

        return "\n".join(render(self.path, full=full, color=False))
