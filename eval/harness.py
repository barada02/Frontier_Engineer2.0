"""Shared evaluation machinery: case setup, the diff under review, and scoring.

The agent reviews a repository sitting at the PARENT of a bug-fix commit, so
the defect is present and the human's regression test is absent. What it is
asked to review is the reverse diff of the fix -- the change that introduces
the bug -- which makes this a pull-request review task rather than a
needle-in-a-haystack hunt.

Scoring never trusts what the agent says. A claim only counts if the test it
writes fails on the buggy tree and passes once the real fix is applied. That
makes the primary metric mechanical: the agent cannot argue its way to a point.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
MAX_DIFF_LINES = 400

# corpus/ is not committed -- these are other people's repositories and they run
# to ~2GB. Cloning on first use is what makes the mining step in REPRODUCE.md
# genuinely optional: cases.json pins exact SHAs, so the checkout is identical
# whether the clone happened during mining or here.
REPO_URLS = {
    "click": "https://github.com/pallets/click.git",
    "more-itertools": "https://github.com/more-itertools/more-itertools.git",
    "attrs": "https://github.com/python-attrs/attrs.git",
}


@dataclass
class Verdict:
    """What a solver claims about a case."""
    verdict: str = "clean"        # "bug" | "clean"
    file: str = ""
    symbol: str = ""
    explanation: str = ""
    test_code: str = ""


@dataclass
class Score:
    case_id: str
    kind: str
    verdict_correct: bool = False
    localized: bool = False
    verified: bool = False        # the proof test actually discriminates
    false_alarm: bool = False
    proof_outcome: str = "none"   # none|verified|no_fail|no_pass|broken
    cost_usd: float = 0.0
    seconds: float = 0.0
    steps: int = 0
    note: str = ""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def ensure_repo(name: str) -> Path:
    """The corpus repository for a case, cloned on first use."""
    dest = CORPUS / name
    if (dest / ".git").exists():
        return dest
    url = REPO_URLS.get(name)
    if url is None:
        raise RuntimeError(
            f"corpus repo {name!r} is missing and no clone URL is known for it")
    print(f"  [corpus] cloning {url} -> {dest} (first use, a few minutes)")
    CORPUS.mkdir(exist_ok=True)
    # blob:none keeps full history metadata but skips file contents until needed.
    subprocess.run(["git", "clone", "--filter=blob:none", url, str(dest)],
                   check=True)
    return dest


@contextlib.contextmanager
def case_workspace(case: dict) -> Iterator[Path]:
    """A throwaway worktree at the buggy state."""
    repo = ensure_repo(case["repo"])
    tmp = Path(tempfile.mkdtemp(prefix="eval_"))
    wt = tmp / "wt"
    base = case["parent"] if case["kind"] == "bug" else case["sha"]
    r = _git(repo, "worktree", "add", "--detach", str(wt), base)
    if r.returncode != 0 or not wt.exists():
        # A failed checkout used to be silent: review_diff would return an empty
        # string and every case would score as a considered miss on a diff that
        # was never shown. A broken environment is not a result.
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(
            f"could not check out {case['case_id']} at {base[:8]}: "
            f"{r.stderr.strip() or 'git worktree add failed'}")
    try:
        yield wt
    finally:
        _git(repo, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(tmp, ignore_errors=True)


def review_diff(case: dict) -> str:
    """The change presented to the agent for review.

    For a bug case this is fixed -> buggy, i.e. the patch that introduces the
    defect. Test files are excluded: the deleted regression test would name the
    answer outright.
    """
    repo = ensure_repo(case["repo"])
    if case["kind"] == "bug":
        a, b = case["sha"], case["parent"]
    else:
        a, b = case["parent"], case["sha"]
    r = _git(repo, "diff", a, b, "--", *case["source_files"])
    if not (r.stdout or "").strip():
        # Every case changes its source files by construction, so an empty diff
        # means the repository is wrong -- not that there is nothing to review.
        raise RuntimeError(
            f"empty review diff for {case['case_id']} ({a[:8]}..{b[:8]}): "
            f"{r.stderr.strip() or 'corpus repo may be at the wrong revision'}")
    lines = (r.stdout or "").splitlines()
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + ["... [diff truncated]"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Proof verification

_PROOF_NAME = "test_agent_proof.py"


def _pytest(wt: Path, target: str, timeout: int = 120) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(wt), str(wt / "src")])
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", target,
             "-q", "--tb=short", "-p", "no:cacheprovider", "--no-header",
             "--timeout=60"],
            cwd=wt, capture_output=True, text=True, env=env, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def _outcome(out: str) -> str:
    if "TIMEOUT" in out:
        return "timeout"
    if re.search(r"\d+ failed", out):
        return "failed"
    if re.search(r"\d+ error", out, re.I):
        return "error"          # could not even import or collect
    if re.search(r"\d+ passed", out):
        return "passed"
    return "unknown"


def verify_proof(case: dict, wt: Path, test_code: str) -> tuple[str, str]:
    """Does the agent's test actually discriminate?

    It must fail on the buggy tree and pass once the genuine fix is applied.
    A test that fails in both states is broken rather than a proof; one that
    passes in both is testing something unrelated to the defect.
    """
    if not test_code.strip():
        return "none", "no test supplied"

    tests_dir = wt / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / _PROOF_NAME).write_text(test_code, encoding="utf-8")
    rel = "tests/" + _PROOF_NAME

    buggy = _outcome(_pytest(wt, rel))
    if buggy in ("error", "timeout", "unknown"):
        return "broken", "buggy run: " + buggy
    if buggy != "failed":
        return "no_fail", "test passes on the buggy code"

    # Apply the real fix, leaving the agent's test in place.
    _git(wt, "checkout", case["sha"], "--", *case["source_files"])
    fixed = _outcome(_pytest(wt, rel))
    _git(wt, "checkout", case["parent"], "--", *case["source_files"])

    if fixed != "passed":
        return "no_pass", "still " + fixed + " after the real fix"
    return "verified", "fails buggy, passes fixed"


# --------------------------------------------------------------------------- #

def _norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("./").lower()


def score_case(case: dict, v: Verdict, wt: Path) -> Score:
    s = Score(case_id=case["case_id"], kind=case["kind"])

    if case["kind"] == "clean":
        s.verdict_correct = v.verdict != "bug"
        s.false_alarm = v.verdict == "bug"
        s.note = "correctly stayed quiet" if s.verdict_correct else "flagged " + v.file
        return s

    s.verdict_correct = v.verdict == "bug"
    truth = {_norm(f) for f in case["source_files"]}
    s.localized = _norm(v.file) in truth if v.file else False

    if s.verdict_correct:
        s.proof_outcome, s.note = verify_proof(case, wt, v.test_code)
        s.verified = s.proof_outcome == "verified"
    else:
        s.note = "missed the bug"
    return s


def aggregate(scores: list[Score]) -> dict:
    bugs = [s for s in scores if s.kind == "bug"]
    cleans = [s for s in scores if s.kind == "clean"]
    n_b, n_c = max(len(bugs), 1), max(len(cleans), 1)
    n_all = max(len(scores), 1)
    return {
        "n_bug": len(bugs),
        "n_clean": len(cleans),
        "verified_detection_rate": sum(s.verified for s in bugs) / n_b,
        "localization_rate": sum(s.localized for s in bugs) / n_b,
        "claimed_detection_rate": sum(s.verdict_correct for s in bugs) / n_b,
        "false_alarm_rate": sum(s.false_alarm for s in cleans) / n_c,
        "total_cost_usd": sum(s.cost_usd for s in scores),
        "cost_per_case": sum(s.cost_usd for s in scores) / n_all,
        "seconds_per_case": sum(s.seconds for s in scores) / n_all,
    }


def render_table(name: str, agg: dict) -> str:
    return (
        "\n=== " + name + " ===\n"
        f"  verified detection   {agg['verified_detection_rate']:6.1%}"
        f"   ({agg['n_bug']} bug cases)   <- primary\n"
        f"  claimed detection    {agg['claimed_detection_rate']:6.1%}"
        f"   (unproven claims included)\n"
        f"  localization         {agg['localization_rate']:6.1%}\n"
        f"  false alarm          {agg['false_alarm_rate']:6.1%}"
        f"   ({agg['n_clean']} clean controls)\n"
        f"  cost / case          ${agg['cost_per_case']:.4f}\n"
        f"  seconds / case       {agg['seconds_per_case']:.1f}\n"
    )


def save_result(name: str, scores: list[Score], agg: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"name": name, "aggregate": agg, "scores": [asdict(s) for s in scores]},
        indent=2))
