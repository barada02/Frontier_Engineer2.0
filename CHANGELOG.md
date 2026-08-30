# Improvement Changelog

How this solution evolved, and what the evidence said at each step.

Every row was produced by the same command against the same 21 cases:

```bash
python eval/run_eval.py --solver <name>
```

Results are written to `eval/results/<name>.json` — aggregate plus per-case
detail — so every number below points at a file rather than at a recollection.

## The metric

**Verified detection rate** is the primary measure: a bug counts only if the
agent's test *fails on the buggy code and passes once the real fix is applied*.
Claims are never taken at face value.

Reported alongside it:

- **Claimed detection** — what the agent asserts, unverified. The gap between
  this and verified detection is how much of the output is noise.
- **False alarm rate** — bugs reported on the 6 clean controls, which are real
  refactors that change working logic.
- **Cost and seconds per case** — whether the improvement is deployable.

## Iterations

| Stage | What was tried and why | Evidence | Decision |
|---|---|---|---|
| **Baseline** | One direct prompt with the diff. No tools, no repo access, no ability to run anything. The obvious first approach, and what any improvement must beat. | verified **60.0%**, claimed **80.0%**, localization **80.0%**, false alarm **16.7%**, $0.0067/case | Established the starting point. The 20-point gap between claimed and verified detection set the direction for everything after. |
| **Iteration 1 — repo access**<br>`agent-read` | The baseline sees only the diff, so it cannot check how a changed function is actually called. Gave the agent `read_file` and `list_dir` against the checkout. | verified **73.3%** (+13.3), claimed 80.0% (unchanged), localization 80.0% (unchanged), false alarm **0.0%** (−16.7), $0.1133/case | **Kept.** The largest single gain. Note what did *not* move: claimed detection and localization were identical. The agent made the same claims about the same files — they simply became correct. Context improved whether findings hold up, not what the agent noticed. |
| **Iteration 2 — execution**<br>`agent-exec` | Reading is not proof. Added `run_proof_test`, which writes the agent's candidate test into the checkout and returns raw pytest output so the agent can tell a real defect from its own broken test. | verified **73.3%** (flat), claimed **73.3%** (−6.7), precision 11/11 vs 11/12, $0.1045/case | **Kept, despite no gain on the primary metric.** Execution found nothing new. What it did was stop the agent making the one claim it could not back: it tried, failed to produce a discriminating test, and stayed quiet. Precision went 91.7% → 100%. Kept because unproven claims are the failure mode this project exists to remove — but reported as flat, because it was. |
| **Iteration 3 — proof required**<br>`agent-proof` | Required the agent to demonstrate a defect before reporting it, and to answer "clean" when it cannot. Expected to convert the remaining unproven claim. | verified **66.7%** (−6.6), claimed 73.3%, $0.1095/case | **Regressed — see below.** The hypothesis was wrong, and the reason is more useful than the result. |

| **Iteration 4 — raised ceiling**<br>`agent-proof --max-steps 40` | Iteration 3's misses stopped at exactly the step limit. Re-ran the identical configuration with the ceiling at 40 to separate budget exhaustion from judgement. | verified **73.3%** (84.6% excluding two runs killed by HTTP 400), false alarm **16.7%** (+16.7), $0.0960/case | **Diagnosis confirmed, change not shipped.** `attrs-97f8d175` recovered, taking 13 proof runs. But the two longest runs overflowed the request and died with `invalid_request`, and the agent used the extra room to talk itself into a false positive on a correct refactor. Net worse than iteration 2. |

## Shipped configuration

`agent-exec` — repo access plus the ability to run its own test, without the
mandatory-proof rule. It matches the best detection rate at 73.3%, is the only
configuration with 100% precision and 0% false alarms, produces no harness
errors, and is the cheapest of the agent variants.

Against the baseline: **verified detection 60.0% → 73.3%**, **false alarms
16.7% → 0.0%**, at 16x the cost per case.

## Why iteration 3 regressed

Requiring proof dropped verified detection from 73.3% to 66.7%. The per-case
data says why, and it is not that the agent became more cautious.

Three of the four misses stopped at **exactly 20 steps** — the configured
ceiling — after 11, 15 and 16 proof attempts respectively:

| Case | Steps | Proof runs | Found by the three earlier configurations? |
|---|---|---|---|
| `attrs-97f8d175` | 20 | 11 | **yes, by all three** |
| `click-bec59289` | 20 | 15 | no |
| `attrs-000c5634` | 20 | 16 | no |

Those runs did not conclude the code was clean. They ran out of budget
mid-investigation, and the harness recorded the resulting silence as a miss —
downstream, indistinguishable from a considered verdict. Only one case is a
true regression: `attrs-97f8d175`, a defect the baseline and both earlier agent
variants all found, lost to exhaustion rather than to judgement.

Two things followed from this. The harness now records *why* a run stopped and
prefixes exhausted runs with `EXHAUSTED:`, so silence from a spent budget can
never again be read as silence from a decision. And iteration 4 re-runs the
same configuration with a raised ceiling to isolate the cause.

## Corpus construction

The case set went through one significant revision, and it is part of the story.

**Clean controls, v1 — rejected.** The first controls were docs, typo and
cleanup commits. The baseline flagged none of them, so the false alarm rate
read 0.0% and measured nothing. Trivially-clean controls cannot detect a
reviewer that cries wolf.

**Clean controls, v2 — kept.** Controls are now selected by counting changed
*statement* lines, ignoring blanks, comments and anything opening with a quote —
a refactor that reflows docstrings looks large in a diff but gives a reviewer
nothing to react to. Threshold is 8 real statement lines. The replacements
touch genuine logic: option flag streamlining in click, a faster `ichunked` in
more-itertools, typing restructuring in attrs.

The same baseline, unchanged, moved from 0.0% to 16.7% false alarm. The metric
was uninformative before this and is informative after it.

## Instrumentation fixes that changed the numbers

**Token accounting reported $0.00.** The Interactions API reports
`total_input_tokens` / `total_output_tokens` / `total_thought_tokens`, not the
`prompt_token_count` / `candidates_token_count` names used by
`generate_content`. Thinking tokens ran roughly 3x visible output tokens and
bill at the output rate, so folding them in silently would have made every cost
figure meaningless.

**Transport failures scored as missed bugs.** A dropped connection raised
through the solver and was recorded as a miss, making results depend on network
luck. Now retried with backoff.

## Main failure mode

**One bug survived every configuration.** `more-itertools-d992be0d`, "Fix
stability in running_min and running_max", was missed by the baseline and by
all four agent variants, including the run that spent 10 proof attempts on it.
Context did not help, execution did not help, and more budget did not help.

The defect is one character. Inside a fifty-line diff that renames `sis` to `s`
and adds explanatory comments, a single comparison changes:

```python
while sis and not sis[-1][1] < value:    # before
while s   and not s[-1][1]  <= value:    # after
```

The consequence is a stability property. `min(x, y)` returns `x` when `x == y`,
so with equal-but-distinct values the buggy version retains the wrong element.
The human's regression test detects it by comparing *types* across
`[0, 0.0, Fraction(0)]` — three values that are all equal and all different.

Everything about this case is adversarial to a reviewer. The semantic change is
one operator, buried in a diff that is overwhelmingly cosmetic. Nothing looks
wrong. And to write a test that catches it, the agent must first suspect that
tie-breaking order is observable at all — before any tool can help. None of the
capabilities added across four iterations supply that suspicion.

That is the honest boundary of this approach: **it makes an agent better at
confirming defects it already suspects, and does nothing for the ones it never
thinks to look for.** Every gain in this project came from converting weak
claims into strong ones or into silence. Not one came from noticing something
new.

## Hot take

**A verification requirement is not free — it spends the same budget the agent
needs to investigate.**

Requiring proof looked like a pure win: make the agent demonstrate a defect and
noise disappears. It did remove noise. It also dropped verified detection from
73.3% to 66.7%, because three runs hit the step ceiling mid-investigation after
11, 15 and 16 proof attempts. Those runs never concluded anything. The harness
recorded their silence as "no bug found", which downstream is indistinguishable
from a considered verdict — the most dangerous kind of failure, because it
looks like an answer.

Raising the ceiling to 40 recovered the lost bug and proved the diagnosis. It
also overflowed the request as tool output accumulated, killing two runs with
HTTP 400, and gave the agent enough room to argue itself into a false positive
on a correct refactor. The step limit had quietly been doing two jobs: bounding
cost, and bounding the agent's opportunity to rationalise.

Three things we would build differently next time:

1. **Never let an exhausted run look like a negative answer.** Distinguish "I
   examined this and found nothing" from "I ran out of room". They demand
   opposite responses from the human reading the output.
2. **Budget the verification separately from the investigation.** One pool
   means a thorough investigation starves its own proof, and vice versa.
3. **Treat a raised ceiling as a change requiring re-measurement, not a free
   parameter.** More room measurably increased both capability and confabulation
   here, and only measurement separated them.
