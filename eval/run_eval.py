"""Run a solver over the case set and produce the comparison table.

    python eval/run_eval.py --solver baseline
    python eval/run_eval.py --solver baseline --limit 4     # quick smoke run

Results land in eval/results/<solver>.json so the changelog can point at a
file rather than at a number someone typed from memory.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Config
from eval import harness
from eval.agent_solver import AgentSolver
from eval.solvers import BaselineSolver

ROOT = Path(__file__).resolve().parent.parent

# Each entry is one row of the improvement changelog. Staging them as config
# on a single agent keeps the comparison fair: only the named capability
# changes between runs.
SOLVERS = {
    "baseline":    lambda cfg: BaselineSolver(cfg),
    "agent-read":  lambda cfg: AgentSolver(cfg, allow_execution=False, require_proof=False),
    "agent-exec":  lambda cfg: AgentSolver(cfg, allow_execution=True,  require_proof=False),
    "agent-proof": lambda cfg: AgentSolver(cfg, allow_execution=True,  require_proof=True),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solver", default="baseline", choices=sorted(SOLVERS))
    ap.add_argument("--cases", type=Path, default=ROOT / "eval/cases.json")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0, help="0 = all cases")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--max-steps", type=int, default=0,
                    help="override the agent step ceiling (0 = config default)")
    args = ap.parse_args()

    cases = json.loads(args.cases.read_text())
    if args.limit:
        # Keep both kinds represented in a smoke run.
        bugs = [c for c in cases if c["kind"] == "bug"][: args.limit]
        cleans = [c for c in cases if c["kind"] == "clean"][: max(1, args.limit // 3)]
        cases = bugs + cleans

    cfg = Config(cache_enabled=not args.no_cache)
    if args.max_steps:
        cfg.max_steps = args.max_steps
    solver = SOLVERS[args.solver](cfg)
    out = args.out or ROOT / f"eval/results/{args.solver}.json"

    print(f"solver={args.solver}  model={cfg.model}  cases={len(cases)}\n")
    scores: list[harness.Score] = []

    for i, case in enumerate(cases, 1):
        label = f"[{i:2}/{len(cases)}] {case['case_id']:30} {case['kind']:5}"
        try:
            with harness.case_workspace(case) as wt:
                diff = harness.review_diff(case)
                verdict, stats = solver.solve(case, wt, diff)
                score = harness.score_case(case, verdict, wt)
        except Exception as e:
            traceback.print_exc(limit=2)
            score = harness.Score(case_id=case["case_id"], kind=case["kind"],
                                  note=f"harness error: {type(e).__name__}: {e}")
            stats = {"seconds": 0.0, "cost_usd": 0.0, "steps": 0}

        score.cost_usd = stats["cost_usd"]
        score.seconds = stats["seconds"]
        score.steps = stats["steps"]
        if stats.get("stopped_because") == "max_steps_exceeded":
            # Ran out of budget mid-investigation. Recorded distinctly so it is
            # never read as the agent having concluded the code was clean.
            score.note = "EXHAUSTED: " + score.note
        scores.append(score)

        if case["kind"] == "bug":
            mark = "VERIFIED" if score.verified else (
                "loc-only" if score.localized else "miss")
            extra = f" runs={stats['proof_runs']}" if stats.get("proof_runs") else ""
            print(f"{label} {mark:9} {score.proof_outcome:9} "
                  f"{score.note[:34]}{extra}")
        else:
            mark = "FALSE-ALARM" if score.false_alarm else "quiet"
            print(f"{label} {mark}")

    agg = harness.aggregate(scores)
    print(harness.render_table(args.solver, agg))
    harness.save_result(args.solver, scores, agg, out)
    print(f"saved -> {out}")


if __name__ == "__main__":
    main()
