"""Single place for every knob. Changing a run means changing this, not the code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / ".cache"
RUNS_DIR = PROJECT_ROOT / "runs"

# USD per 1M tokens. Source: https://ai.google.dev/gemini-api/docs/pricing
# gemini-3.7-flash promo pricing holds through 2026-12-31, then doubles.
PRICING = {
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}


@dataclass
class Config:
    model: str = os.getenv("MODEL", "gemini-3.7-flash")
    max_steps: int = 20          # hard stop on the agent loop
    max_retries: int = 5         # per LLM call, on 429/5xx
    cache_enabled: bool = True
    workspace: Path = field(default_factory=Path.cwd)

    def price(self) -> tuple[float, float]:
        return PRICING.get(self.model, (0.0, 0.0))
