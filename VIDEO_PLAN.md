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
- [ ] Open `slides.html`, press **F11**, then **C** to hide the counter
- [ ] Be online the first time — the deck pulls IBM Plex from Google Fonts
- [ ] `git status` is clean (so stray demo files are obvious afterwards)
- [ ] `.env` has a working `GEMINI_API_KEY` (only needed for Take 5)
- [ ] Read the script aloud with a stopwatch. If over 5:00, cut from §8.

---

## 1. What you are recording

Two sources, cut together in the editor:

| Source | What it is |
|---|---|
| **Terminal** | five takes of real commands, below |
| **`slides.html`** | nine slides, keyboard-driven, full screen |

### Terminal setup

| Setting | Value |
|---|---|
| Terminal | Windows Terminal (not `cmd.exe` — no ANSI) |
| Font | Cascadia Mono, **20pt** |
| Window | **100+ columns** × ~32 rows |
| Theme | dark, high contrast |
| Recorder | OBS, display capture cropped to the terminal, 1080p30 |

Check the replay fits before you record anything:

```powershell
python -m core.replay runs/agent-exec_more-itertools-f51a53bf.jsonl --width 78
```

Every line must sit on one row. **If characters look eaten**, your terminal is
counting colour escape bytes toward the wrap — add `--no-color`. You lose the
colours, not the `[CODE AT FAULT]` labels.

### Deck controls

| Key | Does |
|---|---|
| `→` / `space` | next slide |
| `←` | previous |
| `1`–`9` | jump to a slide — use this between takes |
| `C` | hide the counter and progress bar — **press before recording** |

Record the deck at your final resolution. Type scales to the window, so
resizing afterwards changes the layout.

---

## 2. The nine slides

| # | Slide | Used in |
|---|---|---|
| 1 | Title — *Prove It* | §1 |
| 2 | The problem — trust asymmetry bars | §1 |
| 3 | The gap — 12 claims, 9 proven, 3 hollow | §3 |
| 4 | The agent — tools, policy gate, scoring | §4 |
| 5 | Ground truth — commit → revert → oracle | §5 |
| 6 | Convergence — the two tests side by side | §6 |
| 7 | Results — the comparison table | §7 |
| 8 | Improvement changelog — four iterations | §8 |
| 9 | Hot take — the quote and the `<` → `<=` diff | §9 |

---

## 3. The five terminal takes

Do not attempt one continuous take. Record each, then cut.

### Take 1 — baseline, live · ~25s · used in §2

```powershell
clear
python eval/run_eval.py --solver baseline --out eval/results/_video_baseline.json
```

Cache-served: all 21 cases in ~20 seconds for $0. Real code running now — this
is your cheapest credibility. Let it reach the summary table.

### Take 2 — the gap · static · used in §3

```powershell
clear
(Get-Content eval/results/baseline_rerun.log) -match "loc-only"
```

```
[ 7/21] click-762c97ee                 bug   loc-only  no_pass   still failed after the real fix
[11/21] click-82f377c5                 bug   loc-only  no_pass   still failed after the real fix
[12/21] more-itertools-be5793a5        bug   loc-only  no_pass   still failed after the real fix
```

`loc-only` = it named the right file. `no_pass` = the test it wrote still
failed after the real fix, so it proves nothing.

> Alternative: skip this and scroll back through Take 1 instead. **Do not pipe
> Take 1** to make that easier — Python block-buffers when its output is not a
> terminal, so the cases would appear in one burst at the end.

### Take 3 — ground truth · static · used in §5

```powershell
clear
git -C corpus/more-itertools show --stat f51a53bf
```

`fix: handle empty interleave_evenly input` — 3 lines of source, 4 lines of
test, one commit. Then reveal the oracle:

```powershell
git -C corpus/more-itertools show f51a53bf -- tests/test_more.py
```

### Take 4 — the execution · ~80s · used in §6 · **the centrepiece**

```powershell
clear
python -m core.replay runs/agent-exec_more-itertools-f51a53bf.jsonl --width 78 --play --speed 1.3
```

A real recorded run, not a re-enactment — which is exactly what deliverable #4
is. Steps 1–3 print `(served from cache)`; leave them in.

### Take 5 — live cutaway · ~10s · optional, ~$0.20

```powershell
clear
python eval/run_eval.py --solver agent-exec --limit 1 --no-cache --out eval/results/_video.json
```

Cut to this for ~8 seconds during Take 4 to prove nothing is staged.

---

## 4. Script

**728 words — 4:51 at 150 wpm.** Bracketed text is a screen cue, not narration.

Sentences are kept short on purpose: mean 8.5 words, none over 21, so it reads
aloud without tripping. **Do not narrate what the slide already says.** Where a
slide is on screen, it carries the detail and the voice carries the argument —
that is why the slide-backed sections below are the short ones.

| § | Screen | Words | Runs |
|---|---|---|---|
| 1 Problem | Slide 1 → Slide 2 | 66 | 0:00–0:26 |
| 2 Baseline | Take 1 | 60 | 0:26–0:52 |
| 3 The gap | Take 2 → Slide 3 | 64 | 0:52–1:18 |
| 4 What we built | Slide 4 | 78 | 1:18–1:50 |
| 5 Ground truth | Take 3 → Slide 5 | 63 | 1:50–2:16 |
| **6 One execution** | **Take 4 → Slide 6** | **193** | **2:16–3:35** |
| 7 Results | Slide 7 | 56 | 3:35–3:58 |
| 8 Changelog | Slide 8 | 60 | 3:58–4:23 |
| 9 Hot take | Slide 9 | 88 | 4:23–5:00 |

### §1 Problem — 0:00–0:26 · *Slide 1, then Slide 2*

> Most teams have switched on an AI code reviewer. Most have quietly stopped
> reading it.
>
> [*slide 2*] Not because it misses bugs. Because it is wrong.
>
> Checking a false alarm takes just as long as checking a real one. After a few
> of those, people stop reading.
>
> So we asked one question. What if a reviewer had to prove a bug before it was
> allowed to report it?

### §2 Baseline — 0:26–0:52 · *Take 1*

> Here's the simple baseline. One prompt, containing the diff. No tools, no
> repository, no ability to run anything — what you reach for first.
>
> Twenty-one cases: fifteen real bugs, six real refactors that are correct. It
> runs in twenty seconds.
>
> [*let it finish*] Eighty percent. It named the right file in twelve of
> fifteen cases. By the usual standard, that's a good reviewer.

### §3 The gap — 0:52–1:18 · *Take 2, then Slide 3*

> But we didn't ask it to name a file. We asked it to write a test that proves
> the bug. So we ran those tests.
>
> [*slide 3*] Three of its twelve findings came with a test that proves
> nothing. It also reported a bug in one refactor that was perfectly correct.
>
> Judge it on whether the findings hold up, and it is a sixty percent
> reviewer.

### §4 What we built — 1:18–1:50 · *Slide 4*

> So here is the agent. It can read the repository, so it sees how the changed
> function is actually used, not just the diff. And it can run its own test.
>
> That last tool returns raw pytest output. That is deliberate. An import error
> means the agent's own test is broken. An assertion failure means the code is
> broken. The agent has to tell those two apart by itself.
>
> And it never scores itself. The harness does that.

### §5 Ground truth — 1:50–2:16 · *Take 3, then Slide 5*

> So the harness needs an answer key. Made-up bugs are too easy, so we use real
> ones.
>
> Every case is a real commit that fixed a bug and added a test for it. We undo
> that commit. The bug comes back, and the test disappears.
>
> [*slide 5*] That deleted test is now our answer key. The agent never sees it.
> Fifteen of seventeen candidates survived.

### §6 One execution — 2:16–3:35 · *Take 4, then Slide 6* · **let it breathe**

> Here it is on one case.
>
> [*steps 1–2*] It reads the source around the change.
>
> [*step 3*] It writes a test and runs it. Fails — but pytest is showing an
> `IndexError` deep inside the library. Ambiguous enough that it keeps digging.
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
> [*step 7*] It files the finding. Seven steps, fifteen seconds. The harness
> then runs that test on the buggy code, applies the real fix, and runs it
> again. Fails, then passes. Verified.
>
> [*slide 6*] And this is the test the human maintainer wrote. We deleted it
> before the agent started. Same two checks, in the same order.
>
> It didn't just find the bug. It rebuilt the check a maintainer thought was
> worth committing.

### §7 Results — 3:35–3:58 · *Slide 7*

> Same cases, same scoring. Sixty percent becomes sixty-seven, or seventy-three.
>
> Two numbers, because we ran it twice and got both. The gap is one case. This
> project is about not taking an agent's word for anything, so we don't get to
> show only our best run.
>
> And false alarms go from one in six, to zero.

### §8 Changelog — 3:58–4:23 · *Slide 8* · **cut here if long**

> Four iterations. The one that mattered most was the first: giving the agent
> the repository. Two more bugs, and every false alarm gone.
>
> But it named the same files as before. The claims just started holding up.
>
> The experiment we removed was requiring proof. Three runs hit the step limit
> while they were still investigating. They never reached a conclusion.

### §9 Hot take — 4:23–5:00 · *Slide 9*

> That looks exactly like the agent deciding the code was fine. It is not the
> same thing. And that is the lesson. Asking for proof is not free. It spends
> the same budget the agent needs in order to investigate.
>
> One bug survived every configuration: one operator, buried in a fifty-line
> cosmetic rename. Catching it means suspecting tie-breaking order is
> observable, before any tool can help.
>
> This makes an agent better at confirming what it already suspects. It does
> nothing for what it never thinks to look for.

---

## 5. Editing

- Cut only on sentence boundaries.
- Speed-ramp dead air in Take 4 at 2–3× with a visible `×3` badge. Never speed
  up silently.
- Zoom to ~130% on the `[CODE AT FAULT]` / `[NO SIGNAL]` lines and on the
  `<` → `<=` diff.
- Hold slides 3, 6 and 7 a beat longer than feels natural — they carry numbers
  people want to read.
- No music under narration. If you want any, keep it to §1 and §9.
- Export 1080p H.264. Confirm the runtime is under 5:00.

## 6. Cleanup before submitting

```powershell
Remove-Item eval/results/_video*.json -Force
git status                          # discard stray runs/ files from Take 5
Remove-Item slides.html -Force
Remove-Item VIDEO_PLAN.md -Force
```

---

**If you run out of time, record §6 properly and treat everything else as
scaffolding.** That section is the video.
