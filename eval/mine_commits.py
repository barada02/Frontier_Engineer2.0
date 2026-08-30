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
CLEAN_RE = re.compile(r"^(refactor|docs?|style|chore|typo|cleanup|rename)\b", re.I)
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

        if CLEAN_RE.match(subject) and source and not tests and len(source) <= 3:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", action="append", required=True,
                    help="name=git_url, repeatable")
    ap.add_argument("--out", type=Path, default=Path("eval/candidates.json"))
    args = ap.parse_args()

    all_c: list[Candidate] = []
    for spec in args.repo:
        name, _, url = spec.partition("=")
        path = clone(url, name)
        found = mine(path, name)
        bugs = [c for c in found if c.kind == "bug"]
        cleans = [c for c in found if c.kind == "clean"]
        print(f"{name:16} {len(bugs):4} bug candidates   {len(cleans):4} clean candidates")
        all_c += found

    args.out.write_text(json.dumps([asdict(c) for c in all_c], indent=2))
    print(f"\ntotal: {sum(c.kind=='bug' for c in all_c)} bug / "
          f"{sum(c.kind=='clean' for c in all_c)} clean -> {args.out}")


if __name__ == "__main__":
    main()
