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
    raw: dict[str, Any] = field(default_factory=dict)

    def cost(self, cfg: Config) -> float:
        pin, pout = cfg.price()
        return (self.input_tokens * pin + self.output_tokens * pout) / 1_000_000


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

_USAGE_INPUT_KEYS = ("input_tokens", "prompt_token_count", "input_token_count")
_USAGE_OUTPUT_KEYS = ("output_tokens", "candidates_token_count", "output_token_count")


def _extract_usage(interaction: Any) -> Usage:
    """Usage field names have moved around across SDK versions, so probe rather
    than assume. The raw blob is kept so a wrong guess is visible in the logs
    instead of silently reporting $0.00."""
    blob = None
    for attr in ("usage", "usage_metadata"):
        blob = getattr(interaction, attr, None)
        if blob is not None:
            break
    if blob is None:
        return Usage()

    d = blob if isinstance(blob, dict) else getattr(blob, "__dict__", {}) or {}
    if hasattr(blob, "model_dump"):
        d = blob.model_dump()

    def pick(keys: tuple[str, ...]) -> int:
        for k in keys:
            v = d.get(k)
            if isinstance(v, int):
                return v
        return 0

    return Usage(pick(_USAGE_INPUT_KEYS), pick(_USAGE_OUTPUT_KEYS), raw=d)


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
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code in (429, 500, 502, 503, 504):
        return True
    return any(k in s for k in ("429", "resource_exhausted", "rate limit",
                                "unavailable", "deadline", "timeout", "503"))
