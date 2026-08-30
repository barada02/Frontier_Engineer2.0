"""Structured run log.

This is submission deliverable #4, not a debugging aid. It is written as the
agent runs so trajectories never have to be reconstructed afterwards, and it
is the evidence every changelog claim points back to.
"""
from __future__ import annotations

import json
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
    cost_usd: float = 0.0
    cache_hits: int = 0
    llm_calls: int = 0
    wall_seconds: float = 0.0


class Trajectory:
    def __init__(self, run_id: str | None = None, meta: dict | None = None):
        RUNS_DIR.mkdir(exist_ok=True)
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = RUNS_DIR / f"{self.run_id}.jsonl"
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

    def render(self) -> str:
        """Human-readable replay — what goes in the submission, not raw JSONL."""
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            k = e["kind"]
            if k == "llm_response":
                if e.get("text"):
                    out.append(f"[{e['elapsed']}s] MODEL: {e['text'][:400]}")
            elif k == "tool_call":
                out.append(f"[{e['elapsed']}s] TOOL  {e['name']}({e['arguments']})")
            elif k == "tool_result":
                out.append(f"           -> {str(e['result'])[:300]}")
            elif k == "approval":
                out.append(f"[{e['elapsed']}s] GATE  {e['name']}: {e['decision']}")
            elif k == "run_end":
                s = e["stats"]
                out.append(f"\n== {e['outcome']} | {s['steps']} steps | "
                           f"{s['input_tokens']}in/{s['output_tokens']}out | "
                           f"${s['cost_usd']:.4f} | {s['wall_seconds']}s")
        return "\n".join(out)
