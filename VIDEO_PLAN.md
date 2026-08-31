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

```bash
python -m core.replay runs/agent-exec_more-itertools-f51a53bf.jsonl --width 78
```

Every line must sit on one row. **If any characters look eaten**, your terminal
is counting colour escape bytes toward the wrap — add `--no-color` and it will
render perfectly. You lose the colours, not the `[CODE AT FAULT]` labels.

---

## 2. Record these takes separately

Do not attempt one continuous take. Record each, then cut in the editor.

### Take 1 — baseline, live · ~25s

```bash
clear
python eval/run_eval.py --solver baseline --out eval/results/_video_baseline.json
```

Cache-served: all 21 cases finish in ~20 seconds for $0. Real code running now —
this is your cheapest credibility. Let it run to the summary table.

### Take 2 — the gap · static

```bash
clear
python -c "import json;[print(f\"{s['case_id']:26} {s['note']}\") for s in json.load(open('eval/results/baseline.json'))['scores'] if s['kind']=='bug' and s['verdict_correct'] and not s['verified']]"
```

Prints the three baseline claims whose tests prove nothing:

```
click-762c97ee             still failed after the real fix
click-82f377c5             still failed after the real fix
more-itertools-be5793a5    still failed after the real fix
```

Hold on screen for the whole of §3.

### Take 3 — ground truth · static

```bash
clear
git -C corpus/more-itertools show --stat f51a53bf
```

Shows `fix: handle empty interleave_evenly input` — 3 lines of source, 4 lines
of test, in one commit. Then reveal the oracle:

```bash
git -C corpus/more-itertools show f51a53bf -- tests/test_more.py
```

Say out loud: this test is deleted before the agent sees anything.

### Take 4 — the execution · ~80s · **the centrepiece**

```bash
clear
python -m core.replay runs/agent-exec_more-itertools-f51a53bf.jsonl \
    --width 78 --play --speed 1.3
```

A real recorded run, not a re-enactment — which is exactly what deliverable #4
is. Steps 1–3 print `(served from cache)`; leave them in, don't hide them.

### Take 5 — live cutaway · ~10s · optional, ~$0.20

```bash
clear
python eval/run_eval.py --solver agent-exec --limit 1 --no-cache \
    --out eval/results/_video.json
```

Cut to this for ~8 seconds during Take 4 to prove nothing is staged.

### Cards — make two, no more

1. **Title card**: project name + one line.
2. **Comparison card**: copy the results table from `README.md` (the
   baseline / run 1 / run 2 table).

---

## 3. Script

~700 words, ~150 wpm. Bracketed text is a screen cue, not narration.

### §1 Problem — 0:00–0:30 · *title card*

> Most teams have switched on an AI code reviewer. Most have quietly stopped
> reading it.
>
> The reason isn't that it misses bugs. It's that it reports things that turn
> out to be nothing. Every false finding costs a human the full price of
> investigating it — and after three or four of those, the tool becomes noise
> you click past.
>
> Trust gets spent faster than it gets earned. So this project asks one
> question: what if a reviewer had to *prove* a bug before it was allowed to
> report one?

### §2 Baseline — 0:30–1:05 · *Take 1*

> Here's the simple baseline. One prompt, containing the diff. No tools, no
> repository, no ability to run anything — what you reach for first.
>
> Twenty-one cases: fifteen real bugs, six real refactors that are correct. It
> runs in twenty seconds.
>
> [*let it finish*] Eighty percent. It named the right file in twelve of
> fifteen cases. By the usual standard, that's a good reviewer.

### §3 The gap — 1:05–1:30 · *Take 2*

> Except we didn't ask it to name a file. We asked it to write a test that
> demonstrates the bug. So we ran those tests.
>
> Three of its twelve findings came with a test that proves nothing. One was a
> bug it invented in code that was correct.
>
> Scored on whether its findings hold up, this is a sixty percent reviewer, and
> a quarter of what it says is wrong. That gap — eighty claimed, sixty proven —
> is the whole problem.

### §4 Ground truth — 1:30–1:55 · *Take 3*

> To measure that you need to know the real answer, and synthetic bugs are too
> easy.
>
> So every case is a real commit from `click`, `more-itertools` or `attrs` that
> fixed a bug *and* added a regression test. We revert it. That puts the bug
> back and deletes the test that catches it.
>
> That deleted test becomes our scoring oracle. The agent never sees it.
> Seventeen candidates, fifteen survived — the rejects had tests that passed
> either way.

### §5 One execution — 1:55–3:15 · *Take 4* · **let the screen breathe**

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

### §6 Comparison — 3:15–3:45 · *comparison card*

> Same cases, same scoring. Verified detection goes from sixty percent to
> sixty-seven or seventy-three.
>
> Two numbers, because we ran it twice and got both. One case of variance, no
> seed available. We're reporting both runs rather than the better one — in a
> project about not taking an agent's word for things, we don't get to headline
> our luckiest result.
>
> False alarms go from one in six to zero. That's the number that decides
> whether anyone keeps the tool switched on.

### §7 Changelog — 3:45–4:30 · *CHANGELOG.md on screen* · **cut here if long**

> Four iterations. The one that mattered most was the first: giving the agent
> the repository. Two more bugs, and every false alarm gone.
>
> But look at what *didn't* move — it made the same claims about the same
> files. They just became correct. Context didn't make it more perceptive. It
> made it more credible.
>
> The experiment we removed was requiring proof. Forcing it to demonstrate
> every bug made things worse. Three runs hit the step ceiling
> mid-investigation, after eleven, fifteen and sixteen attempts. They never
> concluded anything — and the harness logged that silence as "no bug found."

### §8 Hot take — 4:30–5:00 · *the `<` → `<=` diff*

> Which is the lesson. A verification requirement isn't free — it spends the
> same budget the agent needs to investigate. The step limit had quietly been
> doing two jobs: bounding cost, and bounding the agent's room to rationalise.
>
> And one bug survived every configuration. One operator, inside a fifty-line
> cosmetic rename. Nothing looks wrong. Catching it means suspecting that
> tie-breaking order is observable — before any tool can help.
>
> This makes an agent better at confirming what it already suspects. It does
> nothing for what it never thinks to look for.

---

## 4. Editing

- Cut only on sentence boundaries.
- Speed-ramp dead air in Take 4 at 2–3× with a visible `×3` badge. Never speed
  up silently.
- Zoom to ~130% on the `[CODE AT FAULT]` / `[NO SIGNAL]` lines and on the
  `<` → `<=` diff.
- No music under narration. If you want any, keep it to §1 and §8.
- Export 1080p H.264. Confirm the runtime is under 5:00 **including cards**.

## 5. Cleanup before submitting

```bash
rm -f eval/results/_video*.json
git status          # discard stray runs/ files from Take 5
rm -f VIDEO_PLAN.md # this file
```

---

**If you run out of time, record §5 properly and treat everything else as
scaffolding.** That section is the video.
