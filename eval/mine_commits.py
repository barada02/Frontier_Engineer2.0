"""Find candidate evaluation cases in a repository's git history.

A usable bug case is a non-merge commit that BOTH fixes source code AND adds
or changes a test. That pairing is what makes the ground truth trustworthy:
a human decided this was a real defect, and left behind an executable oracle
that proves it. Reverting the whole commit reintroduces the bug and removes
the test, so the agent must find the defect by reasoning rather than by
running a suite that is already red.

This script only mines candidates. It does not verify that the oracle
actually discriminates -- that requires execution and lives in build_cases.py.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "corpus"

BUG_RE = re.compile(r"\b(fix|fixes|fixed|bug|regression|broken|incorrect)\b", re.I)
# A useful control is a change that touches real logic and is still correct --
# the kind of PR a reviewer might cry wolf at. Docs and typo commits are
# trivially clean and produce no signal, so they are excluded rather than used.
DOCS_ONLY_RE = re.compile(r"\b(docs?|changelog|readme|typo|comment|spelling|"
                          r"whitespace|formatting|license)\b", re.I)
# Commits that say "fix" but are not code defects.
NOT_A_BUG_RE = re.compile(r"\b(typo|docs?|changelog|lint|format|ci|test[s]? only|"
                          r"coverage|readme|comment)\b", re.I)

TEST_PATH_RE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]+\.py$|_test\.py$")


@dataclass
class Candidate:
    repo: str
    sha: str
    parent: str
    subject: str
    source_files: list[str]
    test_files: list[str]
    kind: str          # "bug" | "clean"
    code_delta: int = 0   # changed statement lines, ignoring comments and docstrings


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, check=True)
    return r.stdout


def clone(url: str, name: str) -> Path:
    dest = CORPUS / name
    if dest.exists():
        return dest
    CORPUS.mkdir(exist_ok=True)
    print(f"cloning {url} -> {dest}")
    # blob:none keeps full history metadata but skips file contents until needed.
    subprocess.run(["git", "clone", "--filter=blob:none", url, str(dest)], check=True)
    return dest


def mine(repo: Path, name: str, limit: int = 4000) -> list[Candidate]:
    raw = _git(repo, "log", "--no-merges", f"-n{limit}",
               "--format=@@@%H|%P|%s", "--name-only")

    out: list[Candidate] = []
    sha = parent = subject = ""
    files: list[str] = []

    def flush() -> None:
        if not sha:
            return
        py = [f for f in files if f.endswith(".py")]
        tests = [f for f in py if TEST_PATH_RE.search(f)]
        source = [f for f in py if f not in tests]

        if (not BUG_RE.search(subject) and not DOCS_ONLY_RE.search(subject)
                and source and not tests and len(source) <= 3):
            out.append(Candidate(name, sha, parent, subject, source, [], "clean"))
            return

        if (BUG_RE.search(subject) and not NOT_A_BUG_RE.search(subject)
                and tests and source and len(source) <= 2 and len(files) <= 6):
            out.append(Candidate(name, sha, parent, subject, source, tests, "bug"))

    for line in raw.splitlines():
        if line.startswith("@@@"):
            flush()
            head, _, subject = line[3:].partition("|")[0], None, ""
            parts = line[3:].split("|", 2)
            sha, parents, subject = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
            parent = parents.split()[0] if parents.strip() else ""
            files = []
        elif line.strip():
            files.append(line.strip())
    flush()
    return [c for c in out if c.parent]


# Comments and any line opening with a quote: docstrings and bare string
# literals reflow constantly during refactors without changing behaviour.
_SKIP_LINE_RE = re.compile(r"""^\s*(#|"|')""")


def code_delta(repo: Path, sha: str, files: list[str]) -> int:
    """Count changed lines that are actually statements.

    A refactor that only reflows docstrings looks large in a diff but gives a
    reviewer nothing to react to, so those must not become controls.
    """
    try:
        diff = _git(repo, "show", sha, "--format=", "--", *files)
    except subprocess.CalledProcessError:
        return 0
    n = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---")) or len(line) < 2:
            continue
        if line[0] not in "+-":
            continue
        body = line[1:]
        if not body.strip() or _SKIP_LINE_RE.match(body):
            continue
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", action="append", required=True,
                    help="name=git_url, repeatable")
    ap.add_argument("--out", type=Path, default=Path("eval/candidates.json"))
    ap.add_argument("--scan-clean", type=int, default=60,
                    help="how many clean candidates per repo to score (network-bound)")
    ap.add_argument("--min-delta", type=int, default=8,
                    help="minimum changed statement lines for a clean control")
    args = ap.parse_args()

    all_c: list[Candidate] = []
    for spec in args.repo:
        name, _, url = spec.partition("=")
        path = clone(url, name)
        found = mine(path, name)
        bugs = [c for c in found if c.kind == "bug"]
        cleans = [c for c in found if c.kind == "clean"]

        # code_delta needs file contents, and a blob:none clone fetches those
        # lazily over the network -- one round trip per commit. Scoring every
        # candidate would take hours, so cap it at the most recent ones, which
        # are also the ones most likely to run under a current interpreter.
        cleans = cleans[: args.scan_clean]
        for i, c in enumerate(cleans, 1):
            c.code_delta = code_delta(path, c.sha, c.source_files)
            if i % 20 == 0:
                print(f"  scored {i}/{len(cleans)} clean candidates", flush=True)
        # Richest logic changes first: those are the controls worth having.
        cleans = sorted([c for c in cleans if c.code_delta >= args.min_delta],
                        key=lambda c: -c.code_delta)[:40]

        print(f"{name:16} {len(bugs):4} bug candidates   {len(cleans):4} clean "
              f"candidates (>={args.min_delta} code lines)")
        all_c += bugs + cleans

    args.out.write_text(json.dumps([asdict(c) for c in all_c], indent=2))
    print(f"\ntotal: {sum(c.kind=='bug' for c in all_c)} bug / "
          f"{sum(c.kind=='clean' for c in all_c)} clean -> {args.out}")


if __name__ == "__main__":
    main()
