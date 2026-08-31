# Solution video — recording plan

Working document. **Not a submission deliverable** — leave it uncommitted, or
delete it before you package the repo.

Target: **under 5:00**. Venv is assumed active, so commands are plain `python`.

---

## ⚠ Read this first

`run_eval.py` writes to `eval/results/<solver>.json` by default. A demo run of
`agent-exec` **will overwrite your committed run-2 evidence**.

Every eval command in this document passes `--out` to a `_video` file. Do not
drop that flag.

---

## 0. Pre-flight checklist

- [ ] `python tests/test_spine.py` → all 10 pass
- [ ] `git status` is clean (so stray demo files are obvious afterwards)
- [ ] `.env` has a working `GEMINI_API_KEY` (only needed for Take 5)
- [ ] Read the script aloud once with a stopwatch. If over 5:00, cut from §7.

## 1. Terminal setup

| Setting | Value |
|---|---|
| Terminal | Windows Terminal (not `cmd.exe` — no ANSI) |
| Font | Cascadia Mono, **20pt** |
| Window | **100+ columns** × ~32 rows |
| Theme | dark, high contrast |
| Recorder | OBS, display capture cropped to the terminal, 1080p30 |

Check the render fits before you record anything:

```powershell
python -m core.replay runs/agent-exec_more-itertools-f51a53bf.jsonl --width 78
```

Every line must sit on one row. **If any characters look eaten**, your terminal
is counting colour escape bytes toward the wrap — add `--no-color` and it will
render perfectly. You lose the colours, not the `[CODE AT FAULT]` labels.

---

## 2. Record these takes separately

Do not attempt one continuous take. Record each, then cut in the editor.

### Take 1 — baseline, live · ~25s

```powershell
clear
python eval/run_eval.py --solver baseline --out eval/results/_video_baseline.json
```

Cache-served: all 21 cases finish in ~20 seconds for $0. Real code running now —
this is your cheapest credibility. Let it run to the summary table.

### Take 2 — the gap · static

The baseline's own run output already contains the evidence, so just filter the
committed log rather than querying the JSON:

```powershell
clear
(Get-Content eval/results/baseline_rerun.log) -match "loc-only"
```

Prints the three baseline claims whose tests prove nothing — in the run's own
words, with case numbers:

```
[ 7/21] click-762c97ee                 bug   loc-only  no_pass   still failed after the real fix
[11/21] click-82f377c5                 bug   loc-only  no_pass   still failed after the real fix
[12/21] more-itertools-be5793a5        bug   loc-only  no_pass   still failed after the real fix
```

`loc-only` means it named the right file. `no_pass` means the test it wrote
still failed after the real fix was applied — so it proves nothing.

Hold on screen for the whole of §3.

> Alternative, if you would rather show it inside Take 1: don't run this at all.
> Scroll back through Take 1's output and highlight the same three lines live.
> **Do not pipe Take 1** to `Tee-Object` or `Select-String` to make that easier —
> Python block-buffers when its output is not a terminal, so the cases would
> appear in one burst at the end instead of scrolling.

### Take 3 — ground truth · static

```powershell
clear
git -C corpus/more-itertools show --stat f51a53bf
```

Shows `fix: handle empty interleave_evenly input` — 3 lines of source, 4 lines
of test, in one commit. Then reveal the oracle:

```powershell
git -C corpus/more-itertools show f51a53bf -- tests/test_more.py
```

Say out loud: this test is deleted before the agent sees anything.

### Take 4 — the execution · ~80s · **the centrepiece**

```powershell
clear
python -m core.replay runs/agent-exec_more-itertools-f51a53bf.jsonl --width 78 --play --speed 1.3
```

A real recorded run, not a re-enactment — which is exactly what deliverable #4
is. Steps 1–3 print `(served from cache)`; leave them in, don't hide them.

### Take 5 — live cutaway · ~10s · optional, ~$0.20

```powershell
clear
python eval/run_eval.py --solver agent-exec --limit 1 --no-cache --out eval/results/_video.json
```

Cut to this for ~8 seconds during Take 4 to prove nothing is staged.

### Cards — make three

1. **Title card**: project name + one line.
2. **Convergence card** — see below. Worth the ten seconds.
3. **Comparison card**: copy the results table from `README.md` (the
   baseline / run 1 / run 2 table).

#### The convergence card

Put these side by side. Left is the human maintainer's regression test, deleted
from the repository before the agent started and never shown to it. Right is
what the agent wrote at step 6, from reasoning alone.

```python
# the human, in commit f51a53bf        |  # the agent, step 6
def test_no_iterables(self):           |  def test_interleave_evenly_empty():
    self.assertEqual(                  |      assert list(
        list(mi.interleave_evenly([])),|          interleave_evenly([])) == []
        [])                            |      assert list(
    self.assertEqual(                  |          interleave_evenly(
        list(mi.interleave_evenly(     |              [], lengths=[])) == []
            [], lengths=[])), [])      |
```

Same two assertions, in the same order, including the non-obvious `lengths=[]`
variant. Pull the left side live with the Take 3 command if you want it on
screen as a terminal rather than a card.

This is the strongest single image in the project: it is the difference between
"the agent found a bug" and "the agent independently reconstructed the check a
human maintainer thought was worth committing." Budget ten seconds for it and
take them from §7.

---

## 3. Script

**723 words, ~4:50 at 150 wpm.** Bracketed text is a screen cue, not narration.
Read it with a stopwatch before recording. §7 is the cut line if you run long.

| § | Words | Runs |
|---|---|---|
| 1 Problem | 72 | 0:00–0:28 |
| 2 Baseline | 60 | 0:28–1:00 |
| 3 The gap | 65 | 1:00–1:26 |
| 4 Ground truth | 62 | 1:26–1:52 |
| **5 One execution** | **244** | **1:52–3:25** |
| 6 Comparison | 70 | 3:25–3:52 |
| 7 Changelog | 78 | 3:52–4:26 |
| 8 Hot take | 72 | 4:26–5:00 |

### §1 Problem — 0:00–0:28 · *title card*

> Most teams have switched on an AI code reviewer. Most have quietly stopped
> reading it.
>
> The reason isn't that it misses bugs. It's that it reports things that turn
> out to be nothing — and every false finding costs a human the full price of
> investigating it.
>
> Trust gets spent faster than it's earned. So: what if a reviewer had to
> *prove* a bug before it was allowed to report one?

### §2 Baseline — 0:28–1:00 · *Take 1*

> Here's the simple baseline. One prompt, containing the diff. No tools, no
> repository, no ability to run anything — what you reach for first.
>
> Twenty-one cases: fifteen real bugs, six real refactors that are correct. It
> runs in twenty seconds.
>
> [*let it finish*] Eighty percent. It named the right file in twelve of
> fifteen cases. By the usual standard, that's a good reviewer.

### §3 The gap — 1:00–1:26 · *Take 2*

> But we didn't ask it to name a file. We asked it to write a test that
> demonstrates the bug. So we ran those tests.
>
> Three of its twelve findings came with a test that proves nothing. One was a
> bug it invented in correct code.
>
> Scored on whether its findings hold up, this is a sixty percent reviewer —
> and a quarter of what it says is wrong.

### §4 Ground truth — 1:26–1:52 · *Take 3*

> To measure that, you need the real answer, and synthetic bugs are too easy.
>
> So every case is a real commit from `click`, `more-itertools` or `attrs` that
> fixed a bug *and* added a regression test. We revert it — putting the bug
> back, and deleting the test that catches it.
>
> That deleted test becomes our oracle. The agent never sees it.

### §5 One execution — 1:52–3:25 · *Take 4* + convergence card · **let it breathe**

> Here's the shipped agent on one case. It reads the repository, and it can run
> its own test.
>
> [*steps 1–2*] It reads the source around the change.
>
> [*step 3*] It writes a test and runs it. Fails — but pytest is showing an
> `IndexError` deep inside the library. The replay flags what that means: code
> at fault, not the test. Ambiguous enough that it keeps digging.
>
> [*step 4 — slow down*] Here it writes something that isn't a test at all. It
> can't read the function body from the diff, so it tries to print the source.
> And pytest says: no signal, nothing was collected.
>
> [*step 5*] It reads that, and wraps the same idea in a real test function to
> force the source out through captured output. Nobody told it to do that. It's
> using a verification tool as a debugger, and it corrected its own mistake in
> one step.
>
> [*step 6*] Now the real test. Fails on the assertion.
>
> [*step 7*] And it files the finding. Seven steps, fifteen seconds.
>
> Then our harness — which never trusts the agent — runs that test on the buggy
> code, applies the real human fix, and runs it again. Fails, then passes.
> Verified.
>
> [*convergence card*] And this is the test the human maintainer wrote, the one
> we deleted before the agent ever started. Same two assertions. Same order.
> Including the second one, with an explicit empty `lengths` argument, which is
> not the obvious thing to check.
>
> It didn't just find the bug. It reconstructed the check a maintainer thought
> was worth committing.

### §6 Comparison — 3:25–3:52 · *comparison card*

> Same cases, same scoring. Verified detection goes from sixty percent to
> sixty-seven or seventy-three.
>
> Two numbers, because we ran it twice and got both. One case of variance, no
> seed available. We report both rather than the better one — in a project
> about not taking an agent's word for things, we don't get to headline our
> luckiest run.
>
> And false alarms go from one in six, to zero.

### §7 Changelog — 3:52–4:26 · *CHANGELOG.md on screen* · **cut here if long**

> Four iterations. The one that mattered most was the first: giving the agent
> the repository. Two more bugs, every false alarm gone.
>
> But notice what didn't move — it made the same claims about the same files.
> They just became correct. Context didn't make it more perceptive. It made it
> more credible.
>
> The experiment we removed was requiring proof. Three runs hit the step
> ceiling mid-investigation and never concluded anything — and the harness
> logged that silence as "no bug found."

### §8 Hot take — 4:26–5:00 · *the `<` → `<=` diff*

> Which is the lesson. A verification requirement isn't free — it spends the
> same budget the agent needs to investigate.
>
> And one bug survived every configuration: a single operator, buried in a
> fifty-line cosmetic rename. Catching it means suspecting that tie-breaking
> order is observable, before any tool can help.
>
> This makes an agent better at confirming what it already suspects. It does
> nothing for what it never thinks to look for.

## 4. Editing

- Cut only on sentence boundaries.
- Speed-ramp dead air in Take 4 at 2–3× with a visible `×3` badge. Never speed
  up silently.
- Zoom to ~130% on the `[CODE AT FAULT]` / `[NO SIGNAL]` lines and on the
  `<` → `<=` diff.
- No music under narration. If you want any, keep it to §1 and §8.
- Export 1080p H.264. Confirm the runtime is under 5:00 **including cards**.

## 5. Cleanup before submitting

```powershell
Remove-Item eval/results/_video*.json -Force
git status                          # discard stray runs/ files from Take 5
Remove-Item VIDEO_PLAN.md -Force    # this file
```

---

**If you run out of time, record §5 properly and treat everything else as
scaffolding.** That section is the video.
