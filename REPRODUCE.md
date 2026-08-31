# Reproduction guide

Written for someone starting from an empty directory and a fresh shell.

## What you need

- **Python 3.11+** (developed on 3.14.3)
- **git 2.30+** (developed on 2.52.0) — `--filter=blob:none` clones are used
- A **Gemini API key** — free tier is sufficient: <https://aistudio.google.com/apikey>
- ~2 GB disk for the three corpus repositories
- Network access to `github.com` and `generativelanguage.googleapis.com`

Developed on Windows 11, and run on Linux and macOS by substituting
`.venv/bin/python` for `.venv/Scripts/python` in every command below. There is
nothing else to change: the harness runs each proof test with `sys.executable`,
so the interpreter you invoke it with is the interpreter the tests run under.

## 1. Install

```bash
git clone <this-repo> && cd Frontier_Engineer2.0
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Pinned versions (`requirements.txt`):

| Package | Version | Note |
|---|---|---|
| `google-genai` | 2.20.0 | uses the `client.interactions` API |
| `python-dotenv` | ≥1.0.0 | |
| `pytest` | **≥8.3, <9** | the upper bound is load-bearing — see below |
| `pytest-timeout` | ≥2.3 | |
| `hypothesis` | ≥6.100 | required by the `attrs` test suite |

> **The pytest pin matters.** pytest 9 promotes `PytestRemovedIn10Warning` to a
> *collection error*, which breaks the older `parametrize` style used in the
> corpus. With pytest 9 installed, cases fail to collect and it looks like the
> corpus is broken. It is a toolchain incompatibility, not a defect in the code
> under test.

## 2. Configure the key

```bash
cp .env.example .env
# edit .env and set GEMINI_API_KEY=...
```

## 3. Verify the install without spending anything

```bash
.venv/Scripts/python tests/test_spine.py
```

Runs the agent loop, tool policies, workspace confinement and cost accounting
against a scripted LLM. **No API key and no network required.** Expected:

```
  multi-step loop            OK
  deny policy                OK
  approval gate (declined)   OK
  workspace confinement      OK
  sibling-prefix escape      OK
  tool error recovery        OK
  max-steps guard            OK
  one file per run           OK
  proof-output triage        OK
  schema generation          OK

all spine tests passed
```

Runtime: under 2 seconds.

## 4. Build the corpus

`eval/cases.json` is committed, so **this step is optional** — skip to step 5
to reproduce the headline result. Step 5 clones the three corpus repositories
itself on first use (`corpus/` is not committed: the repositories belong to
their authors and run to ~2 GB), and `cases.json` pins exact commit SHAs, so
the checkout is identical either way. Expect ~5 minutes of cloning on the first
case of the first run. Run this step only to rebuild the case set from scratch.

```bash
.venv/Scripts/python eval/mine_commits.py \
  --repo click=https://github.com/pallets/click.git \
  --repo more-itertools=https://github.com/more-itertools/more-itertools.git \
  --repo attrs=https://github.com/python-attrs/attrs.git

.venv/Scripts/python eval/build_cases.py --want 15 --want-clean 6 \
  --attempts 70 --timeout 400
```

Runtime: ~5 min to clone, ~10 min to validate. No API cost — this step runs
tests, it does not call a model.

Corpus commits used during development:

| Repo | HEAD |
|---|---|
| `click` | `36baa15` |
| `more-itertools` | `2fe1b2e` |
| `attrs` | `764bf92` |

Mining from newer HEADs will produce a different case set and therefore
different numbers. To reproduce the figures in the README, use the committed
`eval/cases.json`.

## 5. Reproduce the headline comparison

```bash
.venv/Scripts/python eval/run_eval.py --solver baseline
.venv/Scripts/python eval/run_eval.py --solver agent-exec
```

| Run | Runtime | Cost |
|---|---|---|
| `baseline` | ~2 min | ~$0.15 |
| `agent-exec` | ~25 min | ~$3 |

Expected output — the last block of each run:

```
=== baseline ===
  verified detection    60.0%   (15 bug cases)   <- primary
  claimed detection     80.0%   (unproven claims included)
  localization          80.0%
  false alarm           16.7%   (6 clean controls)

=== agent-exec ===
  verified detection    66.7%   (15 bug cases)   <- primary
  claimed detection     73.3%   (unproven claims included)
  localization          73.3%
  false alarm            0.0%   (6 clean controls)
```

The `agent-exec` block above is run 2. This configuration was run twice on
identical inputs and scored 73.3% and 66.7% — one case apart, which is the
expected variance described below. Both runs are kept as evidence, in
`eval/results/agent-exec-run1.json` and `agent-exec-run2.json`, and both are
reported in the README. **Expect your own run to land at either figure.** A
result of 66.7% or 73.3% reproduces this work; 40% does not.

Results are written to `eval/results/<solver>.json` — aggregate plus per-case
detail — so re-running `agent-exec` overwrites `agent-exec.json` (currently a
copy of run 2) and leaves the two archived runs untouched. Agent trajectories
land in `runs/` as JSONL, one file per case.

## 6. Reproduce the other iterations (optional)

```bash
.venv/Scripts/python eval/run_eval.py --solver agent-read
.venv/Scripts/python eval/run_eval.py --solver agent-proof
.venv/Scripts/python eval/run_eval.py --solver agent-proof --max-steps 40 \
    --out eval/results/agent-proof-40.json
```

~25 min and ~$3 each. These correspond to iterations 1, 3 and 4 in
[`CHANGELOG.md`](CHANGELOG.md).

## Caching

Every model response is cached to `.cache/`, keyed by a SHA-256 of the request
(model + full history + tool declarations). A repeat run is billed **$0.00 by
the provider** and completes in seconds.

The cost the harness *reports* is not $0.00, and that is deliberate: a cached
response carries the token counts of the call that produced it, so the figure
answers "what does this configuration cost to run" rather than "what was this
replay charged". Both solvers now count it that way. Force fresh calls with
`--no-cache`.

Cache hits are not all-or-nothing. The first steps of a run are a pure
function of the system prompt and the diff, so they hit even when the run as a
whole is fresh; histories diverge later because pytest output carries elapsed
times. In the recorded `agent-exec` run 2, 84 of 259 model calls were served
from cache.

## Expected variation

The model is not deterministic, and the API offers no seed. Re-running
uncached will move the numbers by roughly one case in either direction —
about ±6.7 percentage points on a 15-case metric. The direction and size of
the baseline-to-agent gap has been stable across runs; a single percentage
point should not be read as meaningful.

Two failure modes seen during development, both handled but worth recognising:

- **`APIConnectionError` / `APITimeoutError`** — retried with exponential
  backoff. Occasional retry lines in the output are normal.
- **`BadRequestError: invalid_request`** — the request outgrew the limit as
  tool output accumulated. The shipped configuration hits this on long runs:
  two cases in `agent-exec` run 1 and one in run 2 died this way, and the
  harness scores them as misses. Expect one or two per full run.

## Total cost of a full reproduction

Baseline plus all four agent variants: **≈ $12** and ≈ 100 minutes.
The headline two-run comparison alone: **≈ $3.2** and ≈ 27 minutes.

Budget above what the recorded runs cost. A clean environment starts with an
empty `.cache/`, so every model call is live; the runs in `eval/results/` had
part of their traffic served from cache and were correspondingly cheaper.
