"""Solvers: the baseline, and (later) the agent.

Both answer the same question about the same cases and emit the same schema,
so the only thing that differs is how they arrive at the answer. The baseline
is deliberately the obvious approach -- one prompt, the diff, no tools, no
ability to run anything -- because that is what a person reaches for first and
what any improvement has to beat.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Config
from core.llm import GeminiLLM
from eval.harness import Verdict

OUTPUT_CONTRACT = """Reply with a single JSON object and nothing else:

{
  "verdict": "bug" or "clean",
  "file": "path/to/the/file/containing/the/defect",
  "symbol": "the function or class at fault",
  "explanation": "one paragraph on what breaks and when",
  "test_code": "a complete pytest module that FAILS on this code and would PASS once the defect is fixed"
}

If the change is fine, use "clean" and leave the other fields empty.
The test module must be self-contained and import the package under review."""

BASELINE_PROMPT = """You are reviewing a proposed change to a Python library.

Decide whether it introduces a bug.

DIFF:
```diff
{diff}
```

{contract}"""


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def parse_verdict(text: str) -> Verdict:
    """Pull the JSON object out of a model reply.

    Models wrap JSON in prose or fences often enough that a bare json.loads
    would throw away otherwise-correct answers and understate every score.
    """
    if not text:
        return Verdict(explanation="empty response")

    candidates = _FENCE_RE.findall(text)
    if not candidates:
        start, depth = text.find("{"), 0
        if start >= 0:
            for i in range(start, len(text)):
                depth += (text[i] == "{") - (text[i] == "}")
                if depth == 0:
                    candidates = [text[start:i + 1]]
                    break

    for blob in candidates:
        try:
            d = json.loads(blob)
        except json.JSONDecodeError:
            continue
        return Verdict(
            verdict="bug" if str(d.get("verdict", "")).lower() == "bug" else "clean",
            file=str(d.get("file") or ""),
            symbol=str(d.get("symbol") or ""),
            explanation=str(d.get("explanation") or ""),
            test_code=str(d.get("test_code") or ""),
        )
    return Verdict(explanation="unparseable response: " + text[:200])


class BaselineSolver:
    """One direct prompt with basic instructions. No tools, no repo, no execution."""

    name = "baseline"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.llm = GeminiLLM(cfg)

    def solve(self, case: dict, workspace: Path, diff: str) -> tuple[Verdict, dict]:
        prompt = BASELINE_PROMPT.format(diff=diff, contract=OUTPUT_CONTRACT)
        history = [{"type": "user_input", "content": [{"type": "text", "text": prompt}]}]

        t0 = time.time()
        resp = self.llm.complete(history, [])
        stats = {
            "seconds": round(time.time() - t0, 2),
            "cost_usd": resp.usage.cost(self.cfg),
            "steps": 1,
        }
        return parse_verdict(resp.text), stats
