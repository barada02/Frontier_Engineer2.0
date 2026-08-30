"""The agent loop.

Deliberately small and owned outright. Every improvement in the changelog is a
change to this file or to the tools it drives, so it stays readable rather than
delegated to a framework.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .config import Config
from .llm import LLM, LLMResponse
from .tools import Decision, Registry
from .trajectory import RunStats, Trajectory


@dataclass
class AgentResult:
    answer: str
    stats: RunStats
    trajectory: Trajectory
    stopped_because: str


def _default_approver(name: str, args: dict) -> bool:
    print(f"\n  APPROVAL REQUIRED -> {name}({json.dumps(args)[:200]})")
    return input("  allow? [y/N] ").strip().lower() in ("y", "yes")


class Agent:
    def __init__(
        self,
        llm: LLM,
        registry: Registry,
        cfg: Config,
        system: str = "",
        approver: Callable[[str, dict], bool] | None = None,
    ):
        self.llm, self.registry, self.cfg = llm, registry, cfg
        self.system = system
        self.approver = approver or _default_approver

    def run(self, task: str, run_id: str | None = None) -> AgentResult:
        traj = Trajectory(run_id, meta={
            "model": self.cfg.model, "task": task,
            "tools": list(self.registry.tools),
        })

        # System text rides as the opening turn rather than a provider-specific
        # field — keeps the history a plain list that any provider can consume.
        history: list[dict] = []
        opening = f"{self.system}\n\n---\n\nTASK: {task}" if self.system else task
        history.append({"type": "user_input",
                        "content": [{"type": "text", "text": opening}]})

        declarations = self.registry.declarations()
        answer, reason = "", "completed"

        for step in range(self.cfg.max_steps):
            resp = self.llm.complete(history, declarations)
            self._account(traj, resp)
            traj.record("llm_response", {
                "step": step, "text": resp.text,
                "tool_calls": [c.name for c in resp.tool_calls],
                "cached": resp.cached,
            })

            history.extend(resp.steps)

            if not resp.tool_calls:
                answer = resp.text
                break

            results = []
            for call in resp.tool_calls:
                results.append(self._execute(traj, call))
            history.extend(results)
        else:
            reason = "max_steps_exceeded"
            answer = resp.text or "(agent hit the step limit without concluding)"

        traj.stats.steps = min(step + 1, self.cfg.max_steps)
        traj.finish(reason, answer[:500])
        return AgentResult(answer, traj.stats, traj, reason)

    # ----------------------------------------------------------------- #

    def _execute(self, traj: Trajectory, call) -> dict:
        decision = self.registry.decide(call.name)
        traj.record("approval", {"name": call.name, "decision": decision.value})

        if decision is Decision.DENY:
            result = f"ERROR: tool '{call.name}' is denied by policy"
        elif decision is Decision.ASK and not self.approver(call.name, call.arguments):
            result = f"ERROR: user declined execution of '{call.name}'"
        else:
            traj.record("tool_call", {"name": call.name, "arguments": call.arguments})
            result = self.registry.invoke(call.name, call.arguments)

        traj.record("tool_result", {"name": call.name, "result": result[:2000]})
        return {
            "type": "function_result",
            "name": call.name,
            "call_id": call.id,
            "result": [{"type": "text", "text": result}],
        }

    def _account(self, traj: Trajectory, resp: LLMResponse) -> None:
        s = traj.stats
        s.llm_calls += 1
        if resp.cached:
            s.cache_hits += 1
            return
        s.input_tokens += resp.usage.input_tokens
        s.output_tokens += resp.usage.output_tokens
        s.cost_usd += resp.usage.cost(self.cfg)
