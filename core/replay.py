"""Turn a trajectory into something a human can actually follow.

Deliverable #4 asks for trajectories that read from the agent's instructions
through to its final result. The JSONL on disk is the record of truth, but it
is not that: 47 lines of nested JSON per case, with the interesting moment --
what pytest said back, and what the agent did about it -- buried inside an
escaped string.

This renders the same file as a transcript, and annotates every proof run with
the distinction the whole design rests on: an import or collection error means
the agent's TEST is wrong, an assertion failure means the CODE is. The agent
has to make that call from raw pytest output, so a reader following the run
should see it being made.

    python -m core.replay runs/<file>.jsonl
    python -m core.replay runs/<file>.jsonl --full
    python -m core.replay runs/<file>.jsonl --play      # paced, for recording
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, Iterator

# Proof-run classification. Order matters: pytest reports "1 failed, 2 passed"
# on a mixed run, and a failure is the signal we care about.
_FAILED_RE = re.compile(r"(\d+) failed")
_ERROR_RE = re.compile(r"(\d+) errors?\b", re.I)
_PASSED_RE = re.compile(r"(\d+) passed")
_IMPORT_ERR_RE = re.compile(r"ImportError|ModuleNotFoundError|error collecting", re.I)

_C = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "cyan": "\033[36m", "yellow": "\033[33m", "green": "\033[32m",
    "red": "\033[31m", "magenta": "\033[35m", "blue": "\033[34m",
}


class Style:
    """Colour that degrades to nothing, so piping to a file stays readable."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, text: str, *names: str) -> str:
        if not self.enabled or not names:
            return text
        return "".join(_C[n] for n in names) + text + _C["reset"]


def classify_proof(output: str) -> tuple[str, str, str]:
    """What pytest said, and what it means about who is at fault.

    Returns (marker, headline, meaning). This is the judgement the agent has
    to make from raw output, restated for the reader rather than inferred by
    the harness -- the harness scores the test separately and never reads this.

    Trajectory records clip tool output at 2000 characters, which sometimes
    cuts off pytest's summary line, so the section headers are used as a
    fallback. Without that, the longest and most interesting runs are the ones
    that read as "no result".
    """
    if "TIMEOUT" in output:
        return "!", "timed out", "the test hangs"
    if "no tests ran" in output:
        return "-", "no tests ran", "nothing was collected"
    if m := _FAILED_RE.search(output):
        return "v", f"{m.group(1)} failed", "assertion failure, not an import error"
    if m := _ERROR_RE.search(output):
        return "x", f"{m.group(1)} error", "import or collection error"
    if m := _PASSED_RE.search(output):
        return "-", f"{m.group(1)} passed", "it demonstrates nothing"
    if "= ERRORS =" in output or _IMPORT_ERR_RE.search(output):
        return "x", "errored (clipped)", "import or collection error"
    if "= FAILURES =" in output:
        return "v", "failed (clipped)", "assertion failure, not an import error"
    return "?", "no result", "no recognisable outcome"


def _columns(items: list[str], width: int) -> list[str]:
    """Pack items two spaces apart, breaking before the terminal would."""
    rows, cur = [], ""
    for it in items:
        candidate = f"{cur}  {it}" if cur else it
        if cur and len(candidate) > width:
            rows.append(cur)
            cur = it
        else:
            cur = candidate
    return rows + [cur] if cur else ["-"]


def _wrap(text: str, width: int, indent: str) -> list[str]:
    out: list[str] = []
    for para in (text or "").splitlines() or [""]:
        out.extend(textwrap.wrap(para, width=width, initial_indent=indent,
                                 subsequent_indent=indent) or [indent.rstrip()])
    return out


def _clip(text: str, limit: int, indent: str, label: str,
          cap: int | None = None) -> list[str]:
    """Clip by line count, and optionally by line length.

    Recorded tool output is foreign text: pytest pads its progress line to
    whatever terminal width the evaluation ran under, which is wider than the
    one replaying it. Without a cap those lines wrap and the transcript stops
    lining up.
    """
    lines = (text or "").splitlines()
    shown = []
    for ln in lines[:limit]:
        ln = ln.rstrip()
        if cap and len(ln) > cap:
            ln = ln[:cap - 3] + "..."
        shown.append(indent + ln)
    if len(lines) > limit:
        shown.append(f"{indent}... {len(lines) - limit} more {label} (--full)")
    return shown


def render(path: Path | str, *, width: int = 96, full: bool = False,
           color: bool = True) -> Iterator[str]:
    """Yield the transcript line by line so a caller can pace or pipe it."""
    s = Style(color)
    path = Path(path)
    events = [json.loads(ln) for ln in
              path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not events:
        yield s(f"{path.name} is empty", "red")
        return

    rule = "=" * width
    body = width - 12
    start = events[0] if events[0].get("kind") == "run_start" else {}

    yield s(rule, "cyan")
    yield s(f" {path.stem}", "bold", "cyan")
    yield s(rule, "cyan")
    if start:
        yield f" {s('model', 'dim')}          {start.get('model', '?')}"
        yield f" {s('step ceiling', 'dim')}   {start.get('max_steps', '?')}"
        yield f" {s('tools', 'dim')}          {', '.join(start.get('tools') or []) or '-'}"
        pol = start.get("policies") or []
        for i, chunk in enumerate(_columns(pol, width - 17)):
            label = "policy" if i == 0 else ""
            yield f" {s(label.ljust(6), 'dim')}         {chunk}"
        yield ""
        yield s(" INSTRUCTIONS GIVEN TO THE AGENT", "bold")
        # Prompts are already hand-wrapped; re-wrapping them strands single
        # words on their own lines and makes the agent's brief look sloppier
        # than it is.
        instr = start.get("system_instructions") or "(none recorded)"
        for ln in _clip(instr, 10_000 if full else 22, "   | ", "lines",
                        cap=width - 5):
            yield s(ln, "dim")
        yield ""
        yield s(" TASK", "bold")
        task = start.get("task") or ""
        head = task.splitlines()[0] if task else "(none)"
        if full:
            for ln in _clip(task, 10_000, "   | ", "lines"):
                yield s(ln, "dim")
        else:
            yield s(f"   | {head}  [{len(task.splitlines())} lines incl. the diff; --full to show]",
                    "dim")

    step = 0
    for e in events:
        kind = e.get("kind")
        at = s(f"[{e.get('elapsed', 0):7.1f}s]", "dim")

        if kind == "llm_response":
            step += 1
            yield ""
            yield s("-" * width, "dim")
            yield f"{at} {s('STEP ' + str(step), 'bold', 'blue')}"
            if e.get("cached"):
                yield s("          (served from cache)", "dim")
            if e.get("text"):
                for ln in _clip("\n".join(_wrap(e["text"], body, "")),
                                10_000 if full else 12, "   ", "lines"):
                    yield s(ln, "cyan")

        elif kind == "approval":
            yield (f"   {s('GATE', 'magenta')}  {e.get('name')} "
                   f"{s('->', 'dim')} {e.get('decision')}")

        elif kind == "tool_call":
            args = e.get("arguments") or {}
            name = e.get("name", "?")
            if "test_code" in args:
                code = args["test_code"] or ""
                yield (f"   {s('CALL', 'yellow', 'bold')}  {name}"
                       f"({s(f'test_code, {len(code.splitlines())} lines', 'dim')})")
                for ln in _clip(code, 10_000 if full else 10, "         ",
                                "lines", cap=width - 9):
                    yield s(ln, "yellow")
            else:
                rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
                yield f"   {s('CALL', 'yellow', 'bold')}  {name}({rendered})"

        elif kind == "tool_result":
            result = str(e.get("result", ""))
            if e.get("name") == "run_proof_test":
                marker, headline, meaning = classify_proof(result)
                tone = {"v": "green", "x": "red", "-": "yellow"}.get(marker, "dim")
                label = {"v": "CODE AT FAULT", "x": "TEST AT FAULT",
                         "-": "NO SIGNAL", "!": "NO SIGNAL"}.get(marker, "UNCLEAR")
                yield f"   {s('->', 'dim')}    pytest: {s(headline, tone, 'bold')}"
                yield "         " + s(f"[{label}]".ljust(16) + meaning, tone)
                for ln in _clip(result, 10_000 if full else 8, "         ",
                                "lines", cap=width - 9):
                    yield s(ln, "dim")
            else:
                for ln in _clip(result, 10_000 if full else 6, "   ->    ",
                                "lines", cap=width - 9):
                    yield s(ln, "dim")

        elif kind == "run_end":
            st = e.get("stats") or {}
            yield ""
            yield s(rule, "cyan")
            outcome = e.get("outcome", "?")
            tone = "red" if outcome != "completed" else "green"
            yield f" {s(outcome.upper(), tone, 'bold')}"
            yield (f" {st.get('steps', '?')} steps · {st.get('llm_calls', '?')} llm calls · "
                   f"{st.get('input_tokens', 0):,} in / {st.get('output_tokens', 0):,} out "
                   f"+ {st.get('thought_tokens', 0):,} thinking")
            yield f" ${st.get('cost_usd', 0):.4f} · {st.get('wall_seconds', 0)}s"
            if e.get("summary"):
                yield ""
                yield s(" FINAL ANSWER", "bold")
                for ln in _clip("\n".join(_wrap(e["summary"], body, "")),
                                10_000 if full else 14, "   | ", "lines"):
                    yield s(ln, "green")
            yield s(rule, "cyan")

    if not any(e.get("kind") == "run_end" for e in events):
        yield ""
        yield s(rule, "red")
        yield s(" NO run_end RECORD -- this run was killed mid-flight.", "red", "bold")
        yield s(" The harness scores it as a miss, which is the safe default but"
                " is not a", "red")
        yield s(" verdict the agent reached. See the HTTP 400 discussion in"
                " CHANGELOG.md.", "red")
        yield s(rule, "red")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("trajectory", type=Path)
    ap.add_argument("--width", type=int, default=96)
    ap.add_argument("--full", action="store_true",
                    help="do not clip instructions, diffs, tests or tool output")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--play", action="store_true",
                    help="pace the output for screen recording")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="multiplier for --play; higher is faster")
    args = ap.parse_args()

    if not args.trajectory.exists():
        raise SystemExit(f"no such trajectory: {args.trajectory}")

    # Box drawing and the middle dot are not in the Windows console's default
    # code page, and a UnicodeEncodeError mid-demo is not a good look.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    color = not args.no_color and sys.stdout.isatty()
    for line in render(args.trajectory, width=args.width, full=args.full,
                       color=color):
        print(line)
        if args.play:
            time.sleep((0.35 if line.strip().startswith("\033[1m\033[34mSTEP")
                        else 0.045) / max(args.speed, 0.01))


if __name__ == "__main__":
    main()
