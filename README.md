# Prove It — a code review agent that has to back up what it says

A review agent that must **demonstrate a defect with a failing test** before it
is allowed to report one, evaluated against 21 real bugs and refactors mined
from the git history of `click`, `more-itertools` and `attrs`.

## Results

Same 21 cases, same task, same scoring, for both configurations.

| Metric | Simple baseline | Agent — run 1 | Agent — run 2 |
|---|---|---|---|
| **Verified detection rate** | **60.0%** (9/15) | **73.3%** (11/15) | **66.7%** (10/15) |
| Precision (proven / claimed) | 75.0% (9/12) | **100%** (11/11) | 90.9% (10/11) |
| False alarm rate | 16.7% (1/6) | **0.0%** (0/6) | **0.0%** (0/6) |
| Localization | 80.0% (12/15) | 73.3% (11/15) | 73.3% (11/15) |
| Cost per case | $0.0067 | ~$0.10 ‡ | ~$0.11 ‡ |
| Seconds per case | 0.9 † | ~72 ‡ | ~46 ‡ |

**Verified detection 60.0% → 66.7–73.3%. False alarms 16.7% → 0.0%.**
Roughly 15–20x the cost per case.

† The baseline row is a cache-served run, so its latency is not comparable; the
uncached timing was not captured. Its cost is, because cached responses carry
the token counts of the original call.

‡ The agent's cost and latency are **floors**, and the two runs are not
comparable to each other on those two rows. 32% of run 2's model calls were
served from the response cache — free and instant — which is most of why it
reads as faster than run 1. Detection, precision and false alarms are
unaffected: those are scored by executing the agent's test against two
revisions of the repository, never by reading the agent's own meter. The
accounting that let cached calls go unbilled is fixed in
[`core/agent.py`](core/agent.py); both recorded runs predate the fix, so the
figures are reported to the precision they can carry rather than to four
decimal places.

**Both runs of the shipped configuration are reported, rather than the better
one.** Same cases, same code, same prompts. The API offers no seed and the
spread is a single case — the ±6.7 points on a 15-case metric that
[`REPRODUCE.md`](REPRODUCE.md) predicts in advance. A project that refuses to
take an agent's word for a finding does not get to headline its luckiest run.
Both runs also lost cases to an HTTP 400 rather than to judgement — two in run
1, one in run 2 — and those are scored as misses, so both numbers are floors.

Evidence: [`agent-exec-run1.json`](eval/results/agent-exec-run1.json) ·
[`agent-exec-run2.json`](eval/results/agent-exec-run2.json) ·
[`baseline.json`](eval/results/baseline.json)

The baseline is one direct prompt containing the diff, with no tools and no
ability to run anything. The shipped agent (`agent-exec`) can read the
repository and run its own candidate test before answering.

**The primary metric is mechanical.** A detection counts only if the agent's
test *fails on the buggy code and passes once the real human fix is applied*.
The agent cannot argue its way to a point.

Full numbers: [`eval/results/`](eval/results/) · Every iteration and what it
taught us: [`CHANGELOG.md`](CHANGELOG.md)

## The problem

**Who has it.** Anyone who reviews pull requests, and anyone who has switched
on an AI reviewer and then quietly stopped reading it.

**The bottleneck.** AI review tools are ignored, and the reason is not that
they miss bugs — it is that they report things that turn out to be nothing.
Every false finding costs a human the full price of investigating it, and after
a few of those the tool becomes noise that people click past. Trust is spent
faster than it is earned.

Our own baseline shows the shape of it. Out of 12 claims it made, **3 were
backed by a test that does not actually demonstrate anything**, and 1 was a bug
invented in a correct refactor. Scored the usual way — "did it name the right
file?" — that baseline looks like an 80% reviewer. Scored on whether its
findings hold up, it is a 60% reviewer, and a quarter of what it says is wrong.

**Why it matters.** A reviewer that reports two provable findings gets read. A
reviewer that reports five findings where one is wrong gets muted. Precision,
not recall, is what determines whether the tool is used at all.

## How it works

```
                 ┌──────────────────────────────────────────┐
   diff  ──────► │  agent                                   │
                 │    read_file / list_dir  ── repo context │
                 │    run_proof_test        ── executes a   │
                 │                             candidate    │
                 │                             test, returns│
                 │                             raw pytest   │
                 │                             output       │
                 └────────────────┬─────────────────────────┘
                                  │  verdict + test
                                  ▼
                 ┌──────────────────────────────────────────┐
   scoring       │  run the test on the buggy tree  → FAIL? │
   (never trusts │  apply the real fix, run again   → PASS? │
    the agent)   │  both hold  ⇒  verified detection        │
                 └──────────────────────────────────────────┘
```

The design choice that matters is that `run_proof_test` returns **raw pytest
output**. The agent has to see *why* its test failed to tell a genuine defect
from its own broken test — an `ImportError` means the test is wrong, an
assertion failure means the code is. That distinction is the entire difference
between a finding and noise.

It shows up as precision: the read-only agent proved 11 of the 12 findings it
claimed, and the executing agent proved 11 of 11 in run 1 and 10 of 11 in run 2.
That is a real effect in the right direction, and it is also one case wide. Two
runs do not separate 91.7% from 100%, and this README will not pretend they do.
What is not noise is the 6-point drop in *claimed* detection: execution is the
only change that made the agent say less.

## Ground truth

The hard part of this problem is knowing the right answer. Synthetic bugs are
easy to generate and easy to detect, which makes them useless as evidence.

Instead, cases are mined from real history. A **bug case** is a commit that
both fixes source code and adds a regression test. Reverting it reintroduces a
defect a human engineer confirmed was worth fixing, and removes the test that
proves it — so the agent must find the bug by reasoning, not by running a suite
that is already red. **The deleted test becomes the scoring oracle and is never
shown to the agent.**

A candidate only becomes a case if its oracle discriminates: fails on the
parent, passes on the fix. **15 of 17 attempts survived** that check. The
rejects are the point — plenty of commits labelled "fix" carry tests that pass
either way, and a case built on one would score the agent against nothing.

**Clean controls** are real refactors that change working logic — option-flag
streamlining in `click`, a faster `ichunked` in `more-itertools`, typing
restructuring in `attrs`. Selected by counting changed *statement* lines,
ignoring comments and docstrings, because a refactor that only reflows prose
gives a reviewer nothing to react to.

The corpus is **21 cases: 15 bugs and 6 controls, 7 from each repository.**

## What we learned

The full account is in [`CHANGELOG.md`](CHANGELOG.md). Three things stand out.

**Context made the agent credible, not perceptive.** Giving it the repository
produced the single largest gain — but claimed detection and localization did
not move at all. It made *the same claims about the same files*; they simply
became correct. Every gain in this project came from converting weak claims
into strong ones or into silence. Not one came from noticing something new.

**Requiring proof made things worse, and the reason is the useful part.**
Mandating a demonstration scored 66.7%, against 73.3% for the read-only agent.
On the aggregate alone that gap is one case and proves nothing. The evidence is
per-case and it is unambiguous: three runs hit
the step ceiling mid-investigation after 11, 15 and 16 proof attempts. They
never concluded anything — the harness recorded their silence as "no bug
found", which downstream is indistinguishable from a considered verdict.
Raising the ceiling recovered the lost bug and confirmed the diagnosis, while
overflowing two runs with HTTP 400 and producing a fresh false alarm on correct
code.

> **A verification requirement is not free — it spends the same budget the
> agent needs to investigate.** The step limit had quietly been doing two jobs:
> bounding cost, and bounding the agent's opportunity to rationalise.

**One bug survived every configuration.** A single operator (`<` → `<=`) hidden
inside a 50-line cosmetic rename, changing which of two equal values a function
returns. Nothing looks wrong, and catching it requires suspecting that
tie-breaking order is observable before any tool can help.

## Reproduction

See [`REPRODUCE.md`](REPRODUCE.md) for setup from a clean environment, exact
commands, expected output, versions, runtime and cost.

The short version:

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
echo "GEMINI_API_KEY=..." > .env
python eval/run_eval.py --solver baseline      # ~2 min,  ~$0.15
python eval/run_eval.py --solver agent-exec    # ~25 min, ~$3
```

Responses are cached to `.cache/` keyed by request hash, so a repeat run costs
nothing and completes in seconds.

## What existed before, and what we built

**Pre-existing:** the `google-genai` SDK; the `click`, `more-itertools` and
`attrs` repositories, used read-only as the corpus; `pytest`.

**Built for this competition:** everything in `core/` and `eval/` — the agent
loop, tool layer, approval policies, trajectory logging, cost accounting and
response cache; the commit miner and case validator; the scoring harness and
its proof-verification mechanism; the baseline and all four agent variants.

## Agents used

| Agent | Role | Disclosed |
|---|---|---|
| Claude Code (Opus) | Wrote this project | Development tool; not part of the submitted system |
| `gemini-3.7-flash` | The reviewing agent under evaluation | The submitted system |

Trajectories for all 21 evaluated cases of the shipped configuration are in
[`runs/`](runs/), emitted automatically by
[`core/trajectory.py`](core/trajectory.py) as the agent executes. Each file
opens with a `run_start` record carrying the system instructions, the tool
list, the policy set and the step ceiling, so a run can be followed from the
agent's instructions through to its final answer without reading the code.

## Safety

Model-written code is executed, which is the one consequential action in this
system. It runs inside a throwaway git worktree, never the working repository,
and is gated by an explicit policy layer:

```python
policies = [deny("*"), allow("read_file"), allow("list_dir"),
            ask_user("run_proof_test")]
```

Batch evaluation auto-approves for reproducibility; the interactive demo prompts
a human before each execution. Filesystem tools are confined to the workspace
root via `Path.is_relative_to`.

## Layout

```
core/          agent loop, tools, policies, trajectories, cost accounting, cache
eval/          corpus construction, scoring harness, baseline and agent solvers
eval/results/  every measured run, aggregate plus per-case detail
tests/         offline spine tests — no API key required
CHANGELOG.md   the improvement log: what was tried, the evidence, the decision
```
