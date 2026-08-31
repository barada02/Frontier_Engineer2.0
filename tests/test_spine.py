"""Offline proof that the agent loop works.

Uses a scripted LLM so the loop, the policy gate, the trajectory log and the
cost accounting are all verified without a network call or an API key. Keeping
this green is what makes provider swaps safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Agent
from core.config import Config
from core.llm import LLMResponse, ToolCall, Usage
from core.tools import Registry, allow, ask_user, deny, make_fs_tools

# runs/ is a tracked submission deliverable. Redirect trajectory output into a
# temp directory so running the tests never leaves stray files there.
import tempfile as _tempfile
from pathlib import Path as _Path

import core.trajectory as _traj

_traj.RUNS_DIR = _Path(_tempfile.mkdtemp(prefix="test_runs_"))


class ScriptedLLM:
    """Replays a fixed list of responses, recording the history it was given."""

    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.seen_histories: list[list[dict]] = []

    def complete(self, history, tools):
        self.seen_histories.append(list(history))
        return self.responses.pop(0)


def _call(name, args, cid="c1"):
    return LLMResponse(
        text="", tool_calls=[ToolCall(cid, name, args)],
        steps=[{"type": "function_call", "id": cid, "name": name, "arguments": args}],
        usage=Usage(1000, 200),
    )


def _final(text):
    return LLMResponse(text=text, tool_calls=[], steps=[{"type": "text", "text": text}],
                       usage=Usage(500, 100))


def build(tmp: Path, responses, approver=None, policies=None):
    cfg = Config(workspace=tmp, cache_enabled=False)
    reg = Registry(make_fs_tools(tmp), policies or
                   [deny("*"), allow("read_file"), allow("list_dir"), ask_user("run_command")])
    return Agent(ScriptedLLM(responses), reg, cfg, system="test", approver=approver), cfg


def test_multi_step_loop(tmp: Path) -> None:
    (tmp / "hello.py").write_text("print('hi')\n")
    agent, cfg = build(tmp, [
        _call("list_dir", {"path": "."}),
        _call("read_file", {"path": "hello.py"}, "c2"),
        _final("SUMMARY: prints hi."),
    ])
    r = agent.run("describe this repo")

    assert r.answer == "SUMMARY: prints hi."
    assert r.stopped_because == "completed"
    assert r.stats.steps == 3 and r.stats.llm_calls == 3
    # 2 tool turns @1000/200 + 1 final @500/100
    assert r.stats.input_tokens == 2500 and r.stats.output_tokens == 500
    assert r.stats.cost_usd > 0
    log = r.trajectory.path.read_text()
    assert "hello.py" in log and "list_dir" in log
    print("  multi-step loop            OK")


def test_denied_tool_is_reported_to_model(tmp: Path) -> None:
    agent, _ = build(tmp, [
        _call("run_command", {"command": "echo hi"}),
        _final("could not run"),
    ], policies=[deny("*")])
    r = agent.run("run something")

    fed_back = agent.llm.seen_histories[-1]
    result = [h for h in fed_back if h.get("type") == "function_result"][-1]
    assert "denied by policy" in result["result"][0]["text"]
    assert r.answer == "could not run"
    print("  deny policy                OK")


def test_ask_user_declined(tmp: Path) -> None:
    agent, _ = build(tmp, [
        _call("run_command", {"command": "echo hi"}),
        _final("user said no"),
    ], approver=lambda n, a: False)
    agent.run("run something")

    result = [h for h in agent.llm.seen_histories[-1]
              if h.get("type") == "function_result"][-1]
    assert "user declined" in result["result"][0]["text"]
    print("  approval gate (declined)   OK")


def test_workspace_escape_blocked(tmp: Path) -> None:
    agent, _ = build(tmp, [
        _call("read_file", {"path": "../../../etc/passwd"}),
        _final("blocked"),
    ])
    agent.run("read outside")

    result = [h for h in agent.llm.seen_histories[-1]
              if h.get("type") == "function_result"][-1]
    assert "escapes workspace" in result["result"][0]["text"]
    print("  workspace confinement      OK")


def test_sibling_prefix_not_treated_as_inside(tmp: Path) -> None:
    """Regression: a string-prefix check let /repo-secret pass a /repo root."""
    root = tmp / "repo"
    root.mkdir()
    sibling = tmp / "repo-secret"
    sibling.mkdir()
    (sibling / "creds.txt").write_text("SECRET")

    cfg = Config(workspace=root, cache_enabled=False)
    reg = Registry(make_fs_tools(root), [allow("*")])
    llm = ScriptedLLM([_call("read_file", {"path": "../repo-secret/creds.txt"}),
                       _final("blocked")])
    Agent(llm, reg, cfg).run("read the sibling")

    result = [h for h in llm.seen_histories[-1]
              if h.get("type") == "function_result"][-1]
    assert "escapes workspace" in result["result"][0]["text"], result
    print("  sibling-prefix escape      OK")


def test_tool_error_recovers(tmp: Path) -> None:
    agent, _ = build(tmp, [
        _call("read_file", {"path": "missing.py"}),
        _final("that file does not exist"),
    ])
    r = agent.run("read a missing file")
    assert r.stopped_because == "completed"
    result = [h for h in agent.llm.seen_histories[-1]
              if h.get("type") == "function_result"][-1]
    assert result["result"][0]["text"].startswith("ERROR:")
    print("  tool error recovery        OK")


def test_max_steps_guard(tmp: Path) -> None:
    cfg = Config(workspace=tmp, cache_enabled=False, max_steps=3)
    reg = Registry(make_fs_tools(tmp), [allow("*")])
    llm = ScriptedLLM([_call("list_dir", {"path": "."}) for _ in range(10)])
    r = Agent(llm, reg, cfg, approver=lambda n, a: True).run("loop forever")
    assert r.stopped_because == "max_steps_exceeded"
    assert r.stats.steps == 3
    print("  max-steps guard            OK")


def test_repeat_runs_get_separate_trajectories() -> None:
    """Regression: records are appended, so a deterministic run_id spliced a
    re-run onto the previous one. Trajectories are a deliverable -- two runs
    must never end up in one file."""
    from core.trajectory import Trajectory

    a = Trajectory("agent-exec_some-case", meta={"n": 1})
    b = Trajectory("agent-exec_some-case", meta={"n": 2})
    try:
        assert a.path != b.path, "repeat run reused the trajectory file"
        for t in (a, b):
            starts = sum(1 for line in t.path.read_text(encoding="utf-8").splitlines()
                         if '"run_start"' in line)
            assert starts == 1, f"{t.path.name} holds {starts} runs"
        print("  one file per run           OK")
    finally:
        for t in (a, b):
            t.path.unlink(missing_ok=True)


def test_proof_output_is_classified_by_fault() -> None:
    """The replay's whole job is showing whose fault a failed proof run is.

    pytest's summary line is sometimes clipped out of a trajectory record, and
    the runs where that happens are the long interesting ones -- so the header
    fallbacks matter more than the happy path."""
    from core.replay import classify_proof

    code_at_fault = ("v", "assertion failure, not an import error")
    test_at_fault = ("x", "import or collection error")

    cases = [
        ("1 failed, 2 passed in 0.4s", code_at_fault),
        ("3 passed in 0.2s", ("-", None)),
        ("1 error in 0.1s\nImportError: no module named foo", test_at_fault),
        ("no tests ran in 0.27s", ("-", None)),
        ("TIMEOUT", ("!", None)),
        # summary clipped by the 2000-char record limit
        ("F  [100%]\n=== FAILURES ===\nE  assert False", code_at_fault),
        ("=== ERRORS ===\nModuleNotFoundError: more_itertools", test_at_fault),
    ]
    for output, (marker, meaning) in cases:
        got_marker, _, got_meaning = classify_proof(output)
        assert got_marker == marker, f"{output!r} -> {got_marker!r}"
        if meaning:
            assert got_meaning == meaning, f"{output!r} -> {got_meaning!r}"

    # A mixed run must read as a failure: one failing assertion is the signal,
    # however many unrelated tests passed alongside it.
    assert classify_proof("1 failed, 9 passed")[0] == "v"
    print("  proof-output triage        OK")


def test_schema_generation() -> None:
    reg = Registry(make_fs_tools(Path.cwd()))
    d = {t["name"]: t for t in reg.declarations()}
    assert d["read_file"]["parameters"]["required"] == ["path"]
    assert d["list_dir"]["parameters"]["required"] == []   # has a default
    assert d["read_file"]["parameters"]["properties"]["path"]["type"] == "string"
    assert d["read_file"]["description"].startswith("Read a UTF-8")
    print("  schema generation          OK")


if __name__ == "__main__":
    import shutil, tempfile

    tests = [test_multi_step_loop, test_denied_tool_is_reported_to_model,
             test_ask_user_declined, test_workspace_escape_blocked,
             test_sibling_prefix_not_treated_as_inside,
             test_tool_error_recovers, test_max_steps_guard]
    for t in tests:
        d = Path(tempfile.mkdtemp())
        try:
            t(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    test_repeat_runs_get_separate_trajectories()
    test_proof_output_is_classified_by_fault()
    test_schema_generation()
    print("\nall spine tests passed")
