"""Milestone 1 — prove the spine works end to end.

Points the agent at a repository and asks it to characterise the codebase,
exercising a multi-step tool loop, the approval gate, the trajectory log and
cost accounting in one run.

    python milestone1.py <repo_path> [--yes] [--no-cache]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from core.agent import Agent
from core.config import Config
from core.llm import GeminiLLM
from core.tools import Registry, allow, ask_user, deny, make_fs_tools

SYSTEM = """You are a senior engineer assessing an unfamiliar codebase.

Work in small steps: list directories, read the files that matter, and use
run_command only when reading is not enough. Do not guess at file contents you
have not read.

When you have enough evidence, stop calling tools and reply with:
  SUMMARY: what this codebase does, in two sentences.
  WEAKEST: the module or file most likely to cause problems, and why.
Cite the specific files that support each claim."""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("--yes", action="store_true", help="auto-approve gated tools")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"not a directory: {repo}")

    cfg = Config(workspace=repo, cache_enabled=not args.no_cache)

    registry = Registry(
        tools=make_fs_tools(repo),
        # Reading is free; anything that executes is gated. This is the
        # hackathon's ground rule #4 expressed as configuration.
        policies=[deny("*"), allow("read_file"), allow("list_dir"),
                  ask_user("run_command")],
    )

    agent = Agent(
        llm=GeminiLLM(cfg),
        registry=registry,
        cfg=cfg,
        system=SYSTEM,
        approver=(lambda n, a: True) if args.yes else None,
    )

    print(f"model={cfg.model}  workspace={repo}  cache={'off' if args.no_cache else 'on'}\n")
    result = agent.run(f"Assess the repository at {repo}")

    print("\n" + "=" * 70)
    print(result.answer)
    print("=" * 70)

    s = result.stats
    print(f"\nsteps: {s.steps} · llm calls: {s.llm_calls} (cache hits {s.cache_hits})")
    print(f"tokens: {s.input_tokens} in / {s.output_tokens} out "
          f"+ {s.thought_tokens} thinking · cost: ${s.cost_usd:.4f}")
    print(f"wall: {s.wall_seconds}s · stopped: {result.stopped_because}")
    print(f"trajectory: {result.trajectory.path}")


if __name__ == "__main__":
    main()
