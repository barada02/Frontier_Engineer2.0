"""The agent solver, staged by capability.

Three variants share one implementation so the comparison stays honest -- each
changelog iteration is a configuration change, not a different program:

    agent-read   repo access, no execution        (can it use context?)
    agent-exec   + can run its own candidate test (can it use feedback?)
    agent-proof  + must prove a bug before claiming one

The last variant is the real hypothesis. The baseline claims 12 bugs and can
only prove 9, because it never runs the test it writes. An agent that executes
its proof and reads the failure should convert most of those unproven claims,
and should stay quiet when it cannot produce a discriminating test.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Agent
from core.config import Config
from core.llm import GeminiLLM
from core.tools import Registry, allow, ask_user, deny, make_fs_tools
from eval.harness import Verdict
from eval.solvers import OUTPUT_CONTRACT, parse_verdict

PROOF_FILE = "tests/test_agent_proof.py"

BASE_ROLE = """You are reviewing a proposed change to a Python library, deciding
whether it introduces a bug.

The repository is checked out at the proposed state, so the code you read is the
code as it would be after this change lands. Read the files the diff touches and
the code around them before deciding. Do not speculate about contents you have
not read."""

EXEC_ROLE = """
You can run your own test against this checkout with run_proof_test. Use it: a
defect you can demonstrate is worth more than one you can describe."""

PROOF_RULE = """
Before you may answer "bug", you must demonstrate it:

1. Write a pytest module that exercises the suspected defect.
2. Run it with run_proof_test.
3. It must FAIL, and fail on an assertion about behaviour -- not on an
   ImportError, a TypeError from calling something the wrong way, or a
   collection error. Those mean your test is wrong, not that the code is.
4. If the failure is your own mistake, fix the test and run it again.

If you cannot produce a test that fails for the right reason, answer "clean".
An unproven suspicion is not a finding. Reporting one costs the reader more
than staying quiet does."""

NO_PROOF_RULE = """
Include a pytest module in test_code that would fail on this defect."""

TASK = """Review this change.

DIFF:
```diff
{diff}
```

{contract}"""


def build_system(allow_execution: bool, require_proof: bool) -> str:
    parts = [BASE_ROLE]
    if allow_execution:
        parts.append(EXEC_ROLE)
    parts.append(PROOF_RULE if require_proof else NO_PROOF_RULE)
    return "\n".join(parts)


def make_proof_tool(workspace: Path, holder: dict):
    """A tool that writes the agent's candidate test and runs it.

    Returning raw pytest output matters: the agent has to see *why* it failed
    to tell a real defect from its own broken test, and that distinction is
    the entire difference between a finding and noise.
    """
    from eval.harness import _pytest

    def run_proof_test(test_code: str) -> str:
        """Write a pytest module and run it against this checkout. Returns pytest output."""
        holder["test_code"] = test_code
        target = workspace / PROOF_FILE
        target.parent.mkdir(exist_ok=True)
        target.write_text(test_code, encoding="utf-8")
        out = _pytest(workspace, PROOF_FILE)
        holder["runs"] = holder.get("runs", 0) + 1
        return out[-4000:] if len(out) > 4000 else out

    return run_proof_test


class AgentSolver:
    name = "agent"

    def __init__(self, cfg: Config, allow_execution: bool = True,
                 require_proof: bool = True, interactive: bool = False,
                 variant: str = "agent"):
        self.name = variant
        self.cfg = cfg
        self.llm = GeminiLLM(cfg)
        self.allow_execution = allow_execution
        self.require_proof = require_proof
        self.interactive = interactive

    def solve(self, case: dict, workspace: Path, diff: str) -> tuple[Verdict, dict]:
        holder: dict = {}
        tools = list(make_fs_tools(workspace))
        # run_command is dropped: the agent gets one narrow execution path
        # instead of a shell, which is easier to sandbox and to audit.
        tools = [t for t in tools if t.__name__ != "run_command"]

        policies = [deny("*"), allow("read_file"), allow("list_dir")]
        if self.allow_execution:
            tools.append(make_proof_tool(workspace, holder))
            # Executing model-written code is the consequential action here, so
            # it is the one gated by policy. Batch evaluation auto-approves for
            # reproducibility; the interactive demo prompts a human.
            policies.append(ask_user("run_proof_test") if self.interactive
                            else allow("run_proof_test"))

        agent = Agent(
            llm=self.llm,
            registry=Registry(tools, policies),
            cfg=self.cfg,
            system=build_system(self.allow_execution, self.require_proof),
            approver=None if self.interactive else (lambda n, a: True),
        )

        t0 = time.time()
        result = agent.run(TASK.format(diff=diff, contract=OUTPUT_CONTRACT),
                           run_id=f"{self.name}_{case['case_id']}")
        verdict = parse_verdict(result.answer)

        # Fall back to the last test the agent actually ran. A model that
        # proved a defect and then omitted the code from its JSON has still
        # done the work, and dropping it would understate the result.
        if not verdict.test_code and holder.get("test_code"):
            verdict.test_code = holder["test_code"]

        return verdict, {
            "seconds": round(time.time() - t0, 2),
            "cost_usd": result.stats.cost_usd,
            "steps": result.stats.steps,
            "proof_runs": holder.get("runs", 0),
            "stopped_because": result.stopped_because,
            "trajectory": str(result.trajectory.path),
        }
