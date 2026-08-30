"""Turn mined commits into verified evaluation cases.

A candidate only becomes a case if its oracle discriminates: the human's
regression test must FAIL on the parent commit and PASS on the fix commit.
Anything else is discarded. Without this gate the ground truth is a guess --
plenty of commits labelled "fix" have tests that pass either way, and a case
built on one of those would score the agent against nothing.

Collection errors are rejected too. An ImportError on the parent means the
commit ADDED a feature rather than fixing a defect, which is a different task
than the one being measured.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"

SUMMARY_RE = re.compile(r"(\d+) (failed|passed|error|errors)")


@dataclass
class Case:
    case_id: str
    repo: str
    kind: str                 # "bug" | "clean"
    sha: str                  # the fix commit
    parent: str               # the buggy state the agent reviews
    subject: str
    source_files: list[str]   # where the defect lives (ground truth)
    test_files: list[str]     # the oracle -- never shown to the agent
    buggy_summary: str = ""
    fixed_summary: str = ""


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


def _parse(out: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n, word in SUMMARY_RE.findall(out):
        counts[word.rstrip("s")] = counts.get(word.rstrip("s"), 0) + int(n)
    return counts


def _pytest(worktree: Path, tests: list[str], py: str, timeout: int) -> tuple[dict, str]:
    """Run the oracle tests from source, no install.

    Pure-Python packages import fine off the tree, so PYTHONPATH beats a
    per-commit editable install -- which would otherwise dominate runtime.
    """
    import os
    env = dict(os.environ)
    paths = [str(worktree), str(worktree / "src")]
    env["PYTHONPATH"] = os.pathsep.join(paths)
    existing = [t for t in tests if (worktree / t).exists()]
    if not existing:
        return {}, "oracle tests missing"
    r = subprocess.run(
        [py, "-m", "pytest", *existing, "-q", "--tb=no", "-p", "no:cacheprovider",
         "--no-header", "-x", "--timeout=60"],
        cwd=worktree, capture_output=True, text=True, env=env, timeout=timeout,
    )
    tail = (r.stdout or "").strip().splitlines()
    return _parse(r.stdout or ""), (tail[-1] if tail else "no output")


def validate(repo: Path, c: dict, py: str, timeout: int) -> Case | None:
    tmp = Path(tempfile.mkdtemp(prefix="case_"))
    wt = tmp / "wt"
    try:
        _run(["git", "worktree", "add", "--detach", str(wt), c["parent"]], repo)

        # Buggy state: parent source, but the fix commit's tests dropped in.
        _run(["git", "checkout", c["sha"], "--", *c["test_files"]], wt)
        buggy, buggy_line = _pytest(wt, c["test_files"], py, timeout)
        if buggy.get("error"):
            return None                      # feature addition, not a defect
        if not buggy.get("failed"):
            return None                      # oracle does not discriminate

        # Fixed state: apply the whole commit.
        _run(["git", "checkout", c["sha"], "--", "."], wt)
        fixed, fixed_line = _pytest(wt, c["test_files"], py, timeout)
        if fixed.get("failed") or fixed.get("error") or not fixed.get("passed"):
            return None                      # flaky or environment-dependent

        return Case(
            case_id=f"{c['repo']}-{c['sha'][:8]}",
            repo=c["repo"], kind="bug", sha=c["sha"], parent=c["parent"],
            subject=c["subject"], source_files=c["source_files"],
            test_files=c["test_files"],
            buggy_summary=buggy_line, fixed_summary=fixed_line,
        )
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    finally:
        _run(["git", "worktree", "remove", "--force", str(wt)], repo)
        shutil.rmtree(tmp, ignore_errors=True)


def _suite_failures(wt: Path, py: str, timeout: int) -> set[str] | None:
    """Return the set of failing test ids, or None if the suite could not run."""
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(wt), str(wt / "src")])
    try:
        r = subprocess.run(
            [py, "-m", "pytest", "-q", "--tb=no", "-rf", "-p", "no:cacheprovider",
             "--no-header", "--timeout=60"],
            cwd=wt, capture_output=True, text=True, env=env, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    out = r.stdout or ""
    if "passed" not in out:
        return None                       # collection blew up entirely
    return {
        line.split(" - ")[0].split(" ", 1)[1].strip()
        for line in out.splitlines()
        if line.startswith(("FAILED ", "ERROR ")) and " " in line
    }


def validate_clean(repo: Path, c: dict, py: str, timeout: int) -> Case | None:
    """A control is only useful if the code there is genuinely healthy.

    Health is measured against the commit's own parent, not against an
    absolutely green suite. Every repo in the corpus carries a few failures
    that depend on the interpreter or the environment rather than on the code
    under test -- click has a 3.14 property issue and shell-completion tests,
    attrs has packaging-metadata tests that need a real install. Demanding a
    perfect suite would silently exclude two of the three repos and leave the
    controls sourced from a single project.

    So: a commit is clean if it introduces no failure its parent did not
    already have. That is also the honest definition of "this change broke
    nothing", which is exactly what a control needs to assert.
    """
    tmp = Path(tempfile.mkdtemp(prefix="clean_"))
    wt = tmp / "wt"
    try:
        _run(["git", "worktree", "add", "--detach", str(wt), c["parent"]], repo)
        before = _suite_failures(wt, py, timeout)
        if before is None:
            return None

        _run(["git", "checkout", c["sha"], "--", "."], wt)
        after = _suite_failures(wt, py, timeout)
        if after is None:
            return None

        introduced = after - before
        if introduced:
            return None

        return Case(
            case_id=f"{c['repo']}-{c['sha'][:8]}-clean",
            repo=c["repo"], kind="clean", sha=c["sha"], parent=c["parent"],
            subject=c["subject"], source_files=c["source_files"], test_files=[],
            fixed_summary=f"{len(after)} pre-existing failures, 0 introduced",
        )
    except Exception:
        return None
    finally:
        _run(["git", "worktree", "remove", "--force", str(wt)], repo)
        shutil.rmtree(tmp, ignore_errors=True)


def interleave(items: list[dict]) -> list[dict]:
    """Round-robin by repo so a case set never comes from one project."""
    from collections import defaultdict
    buckets: dict[str, list[dict]] = defaultdict(list)
    for i in items:
        buckets[i["repo"]].append(i)
    out, queues = [], list(buckets.values())
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=Path, default=ROOT / "eval/candidates.json")
    ap.add_argument("--out", type=Path, default=ROOT / "eval/cases.json")
    ap.add_argument("--python", default=str(ROOT / ".venv/Scripts/python.exe"))
    ap.add_argument("--want", type=int, default=15, help="verified bug cases to collect")
    ap.add_argument("--want-clean", type=int, default=5)
    ap.add_argument("--attempts", type=int, default=60)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    cands = json.loads(args.candidates.read_text())
    bugs = interleave([c for c in cands if c["kind"] == "bug"])
    cleans = interleave([c for c in cands if c["kind"] == "clean"])

    verified: list[Case] = []
    tried = 0
    for c in bugs:
        if len(verified) >= args.want or tried >= args.attempts:
            break
        tried += 1
        case = validate(CORPUS / c["repo"], c, args.python, args.timeout)
        mark = "OK " if case else "-- "
        print(f"{mark}[{len(verified):2}/{args.want}] {c['repo']:15} "
              f"{c['sha'][:8]} {c['subject'][:60]}")
        if case:
            verified.append(case)

    print()
    controls: list[Case] = []
    tried_clean = 0
    for c in cleans:
        if len(controls) >= args.want_clean or tried_clean >= args.attempts:
            break
        tried_clean += 1
        case = validate_clean(CORPUS / c["repo"], c, args.python, args.timeout)
        mark = "OK " if case else "-- "
        print(f"{mark}[{len(controls):2}/{args.want_clean}] CLEAN {c['repo']:15} "
              f"{c['sha'][:8]} {c['subject'][:55]}")
        if case:
            controls.append(case)

    allc = verified + controls
    args.out.write_text(json.dumps([asdict(v) for v in allc], indent=2))
    by_repo: dict[str, int] = {}
    for v in allc:
        by_repo[v.repo] = by_repo.get(v.repo, 0) + 1
    print(f"{len(verified)} bug (of {tried} tried) + {len(controls)} clean "
          f"(of {tried_clean} tried)")
    print(f"by repo: {by_repo}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
