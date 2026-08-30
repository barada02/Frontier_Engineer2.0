"""Provider boundary.

Everything above this file speaks in LLMResponse/ToolCall and never imports a
vendor SDK. That is what makes the Claude swap a config change instead of a
rewrite, and what lets the disk cache be provider-agnostic.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import CACHE_DIR, Config


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0      # billed at the output rate, and usually dominates
    cached_tokens: int = 0
    tool_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def billed_output(self) -> int:
        return self.output_tokens + self.thought_tokens

    def cost(self, cfg: Config) -> float:
        pin, pout = cfg.price()
        return (self.input_tokens * pin + self.billed_output * pout) / 1_000_000


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    steps: list[dict]          # raw provider steps, replayed into history verbatim
    usage: Usage
    cached: bool = False


class LLM(Protocol):
    def complete(self, history: list[dict], tools: list[dict]) -> LLMResponse: ...


# --------------------------------------------------------------------------- #

# Field names confirmed against google-genai 2.20.0 by inspecting a live
# Interaction. The Interactions API reports totals, not the prompt/candidates
# names used by generate_content.
_USAGE_FIELDS = {
    "input_tokens": ("total_input_tokens", "prompt_token_count", "input_tokens"),
    "output_tokens": ("total_output_tokens", "response_token_count", "output_tokens"),
    "thought_tokens": ("total_thought_tokens", "thoughts_token_count"),
    "cached_tokens": ("total_cached_tokens", "cached_content_token_count"),
    "tool_tokens": ("total_tool_use_tokens", "tool_use_prompt_token_count"),
}


def _extract_usage(interaction: Any) -> Usage:
    """Map provider usage onto our own shape.

    Thought tokens are tracked separately and billed as output: on a thinking
    model they routinely outnumber visible output tokens by ~50x, so folding
    them in silently would make every cost figure meaningless.
    """
    blob = getattr(interaction, "usage", None) or getattr(interaction, "usage_metadata", None)
    if blob is None:
        return Usage()

    d = blob.model_dump() if hasattr(blob, "model_dump") else dict(
        blob if isinstance(blob, dict) else getattr(blob, "__dict__", {}) or {})

    vals = {}
    for field_name, candidates in _USAGE_FIELDS.items():
        vals[field_name] = next(
            (d[k] for k in candidates if isinstance(d.get(k), int)), 0)

    if vals["input_tokens"] == 0 and vals["output_tokens"] == 0:
        # Loud rather than a silent $0.00 — the shape changed under us.
        print(f"  [llm] WARNING: could not read usage from {sorted(d)}")

    return Usage(**vals, raw=d)


def _as_dict(step: Any) -> dict:
    if isinstance(step, dict):
        return step
    if hasattr(step, "model_dump"):
        return step.model_dump()
    return dict(getattr(step, "__dict__", {}))


class GeminiLLM:
    """google-genai behind the LLM protocol.

    Runs stateless (store=False) so the full history lives in our process. That
    is a deliberate choice: it makes every request a pure function of its input,
    which is what the cache and the trajectory log both depend on.
    """

    def __init__(self, cfg: Config):
        from google import genai  # imported late so --help works without a key

        self.cfg = cfg
        self.client = genai.Client()
        CACHE_DIR.mkdir(exist_ok=True)

    def _cache_key(self, history: list[dict], tools: list[dict]) -> str:
        payload = json.dumps(
            {"m": self.cfg.model, "h": history, "t": tools},
            sort_keys=True, default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def complete(self, history: list[dict], tools: list[dict]) -> LLMResponse:
        key = self._cache_key(history, tools)
        path = CACHE_DIR / f"{key}.json"

        if self.cfg.cache_enabled and path.exists():
            d = json.loads(path.read_text())
            return LLMResponse(
                text=d["text"],
                tool_calls=[ToolCall(**c) for c in d["tool_calls"]],
                steps=d["steps"],
                usage=Usage(**d["usage"]),
                cached=True,
            )

        interaction = self._call_with_retry(history, tools)

        steps = [_as_dict(s) for s in (interaction.steps or [])]
        calls = [
            ToolCall(id=s.get("id", ""), name=s.get("name", ""),
                     arguments=s.get("arguments") or {})
            for s in steps
            if s.get("type") == "function_call"
        ]
        resp = LLMResponse(
            text=interaction.output_text or "",
            tool_calls=calls,
            steps=steps,
            usage=_extract_usage(interaction),
        )

        if self.cfg.cache_enabled:
            path.write_text(json.dumps({
                "text": resp.text,
                "tool_calls": [c.__dict__ for c in resp.tool_calls],
                "steps": resp.steps,
                "usage": resp.usage.__dict__,
            }, default=str))
        return resp

    def _call_with_retry(self, history: list[dict], tools: list[dict]) -> Any:
        """Free-tier rate limits are low enough that a 20-case eval will hit
        them. Backoff here is not defensive padding; without it the harness
        cannot complete a full run."""
        last: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            try:
                return self.client.interactions.create(
                    model=self.cfg.model,
                    input=history,
                    tools=tools,
                    store=False,
                )
            except Exception as e:  # SDK exception types vary by version
                last = e
                if not _is_retryable(e) or attempt == self.cfg.max_retries - 1:
                    raise
                delay = (2 ** attempt) + random.random()
                print(f"  [llm] {type(e).__name__} — retry in {delay:.1f}s")
                time.sleep(delay)
        raise last  # unreachable, keeps type checkers happy


def _is_retryable(e: Exception) -> bool:
    s = str(e).lower()
    name = type(e).__name__.lower()
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code in (429, 500, 502, 503, 504):
        return True
    # Transport failures are retryable too. A dropped connection mid-run
    # otherwise scores as a missed bug, which silently understates the agent
    # and makes results depend on network luck rather than on the model.
    if any(k in name for k in ("connection", "timeout", "ratelimit")):
        return True
    return any(k in s for k in ("429", "resource_exhausted", "rate limit",
                                "unavailable", "deadline", "timeout", "503",
                                "forcibly closed", "connection reset",
                                "connection aborted", "10054", "eof"))
