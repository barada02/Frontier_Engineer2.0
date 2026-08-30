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
| **Iteration 1 — repo access** | The baseline sees only the diff, so it cannot check how a changed function is actually called. Gave the agent `read_file` and `list_dir` against the checkout. | _pending_ | _pending_ |
| **Iteration 2 — execution** | Reading is not proof. Added `run_proof_test`, which writes the agent's candidate test into the checkout and returns raw pytest output. | _pending_ | _pending_ |
| **Iteration 3 — proof required** | Three of the baseline's twelve claims were backed by a test that does not discriminate. Required the agent to demonstrate a defect before reporting it, and to answer "clean" when it cannot. | _pending_ | _pending_ |

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

_pending — to be written from the per-case results once the iterations complete._

## Hot take

_pending._
