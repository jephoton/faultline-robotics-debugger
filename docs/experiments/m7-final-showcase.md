# M7: final showcase runs (October 19, 2026)

**Status:** complete (October 19, 2026).

**Scope (Jethro, October 19):** the gallery shows fresh cases made by the
single diagnosis pipeline (ADR 0035). Each case is replayed on the same
checkpoint to show the regression loop (ADR 0034):
1. **Probe route.** LIBERO-Object task 0, start 0, with the four default image
   families. Approved with a US$4 total that includes its replay.
2. **Layout route.** LIBERO-10 task 0, start 14 on image v17, then a replay.
   Approved with a US$3.70 maximum. It replaces `FL-S-AFB5`.
3. **Kept:** `FL-A-F526` (LIBERO-Spatial, four image families, nothing broke
   it).

The September occlusion case (`FL-M-52D8`), `FL-A-08D3` and `FL-A-A70E` stay
in the local library but leave the gallery.

## Image v17

v17 carries the October 18 reduction fix (`9d0522e`: keep a verified shrink
when the budget ends between a speculative pair). Without it, a reduction cut
by the budget could report a 100% shrink.

**How it was built.** v16 was built from `eeec427`, and `deploy/` has not
changed since. A full rebuild found Docker's build cache empty and began
reinstalling the model dependencies. The local disk had about 19 GB free, so
the build was stopped. v17 was built instead as an overlay on v16:
- it removes `src/`, `scripts/` and `configs/`, then copies them from
  `ab82017`;
- it reruns the import checks.

The dependency layers are v16's, unchanged, so only the code layers were
pushed. The overlay Dockerfile is not committed; it repeats the tail of
`deploy/serverless/Dockerfile`. A clean rebuild from
`deploy/serverless/Dockerfile` at the same commit should give the same
application files.

## Run 1: probe route (LIBERO-Object task 0, start 0)

Run `object-start0-20261019T021756Z`, started from the control panel with
the defaults (US$2.50 cap, 1.5 hours) on v16.

| Step | Wall clock | Container | Cost |
| --- | --- | --- | --- |
| Check (screen Job) | 16 min (5.3 min to start, 8.1 running, about 2.4 to read the results) | 8.1 min | US$0.35 |
| Probe Job (blur, noise, darken, contrast) | 30 min | 6.5 min of timed testing (135 episodes, 20.9/min), 5.6 min model prefetch | US$0.54 |
| **Total** | **36.5 min** | | **US$0.90** |

The start passed untouched (0 of 5 failed), so the run took the probe route.
That was faster than the Review's typical estimate of about 45 minutes.

**Case `FL-A-D582`:**

| Family | Result | Levels in the order tried (failures/attempts) |
| --- | --- | --- |
| Gaussian blur | fails from s = 0.4625 (sigma 3.70 px) | 0.2: 0/5, 0.4: 1/5, 0.6: 4/5, 0.5: 4/5, 0.45: 1/5, 0.475: 4/5, 0.4625: 5/5 |
| Gaussian noise | fails from s = 1.0 (sigma 100 of 255) | 0.2–0.6: 0/5, 0.8: 1/5, 1: 4/5, then 0.9–0.9875: 3/5 each |
| Darkening | no failure up to s = 1 | all 0/5 |
| Contrast reduction | no failure up to s = 1 | all 0/5 |

The research step attached 13 public sources (Tavily, summarised by Nemotron
3 Nano) as context.

### Replay of `FL-A-D582` (same checkpoint)

The replay was run from the case's Regression test section on image v17. It
was v17's first cloud use, and it worked: 8.0 container minutes, US$0.35.
Verdict: **still fails**.
- Control: 0 of 5 failed.
- Blur at s = 0.4625: 4 of 5 failed (the gate is met).
- Noise at s = 1.0: 3 of 5 failed (the gate is not met).

Noise sat at the edge of the gate in the original search: 4 of 5 at s = 1,
and 3 of 5 at every bisection level. Its threshold should be read as
borderline. Blur is the robust finding.

Run 1 and its replay together cost **US$1.25** of the US$4 approved.

The replay result does not name a checkpoint, because stress-test cases do
not record one. The UI shows "checkpoint not recorded".

## Run 2: layout route (LIBERO-10 task 0, start 14)

Run `l10-start14-20261019T032219Z`, started from the control panel on image
v17. It used the default US$2.50 cap and 1.5 hours, raised by hand to US$3.20
and 3 hours with Jethro's approval.

| Step | Cost |
| --- | --- |
| Check (screen Job): start 14 failed 4 of 5 | US$0.47 |
| Reduction Job: 36 candidates, stopped at the candidate budget | US$0.80 |
| Continuation Job: the remaining shrink steps | US$0.98 |
| **Total** | **US$2.25** |

**Two interrupted downloads.** The reduction Job finished and exported 1,281
files. The download then dropped with `EndpointConnectionError`: first after
578 files, and again on the first resume after 745. The machine's network was
unstable at the time, with Avast's web shield active and DNS failures. Each
time, the run marked the paid Job failed.

Recovery: the attempt was set back to re-attachable by hand (backups kept).
Then 2b19cb5 added per-object download retries and kept complete files, and
the second resume downloaded everything. The Job was not run or paid for
again. The polish pass then made both fixes permanent:
- a failed download keeps the attempt re-attachable (`download_failed`);
- a resume can raise the cap or hour limit.

**Case `FL-S-8E0D`.**
- Reference: start 4.
- The two starts differ in five entities.
- Entity-minimal set: four shifts needed together.
  - basket 2.1 cm (93.8% of its difference);
  - milk 2.2 cm (87.5%);
  - orange juice 0.8 cm (100%, not shrunk before the budget ended);
  - the arm's 5 joints, up to 2.1° (93.8%).

The October 18 reduction fix works here. Verified shrinks are kept, unlike
`FL-S-AFB5`, whose sizes stayed at 100%. Nemotron 3 Ultra ranked the arm
first and the soup second. The arm is necessary but not sufficient, and the
soup is not in the final set.

**Limit (rows 30–31).** The basket at 81.25% also failed 4 of 5, but the
size search kept 93.75%. At 87.5% it had failed only 2 of 4, and bisection
assumes monotone outcomes. Kept sizes are verified to reproduce, but they are
not always the smallest that do.

The case replaces `FL-S-AFB5` in the gallery and in `demo/root`. The bundled
copy originally left out `research.json`, because it held third-party search
snippets. The October 19 cleanup added a sanitized copy with accepted next
steps and source titles/URLs only; no search snippets are bundled. See the
[publication record](m7-public-gallery.md).

### Replay of `FL-S-8E0D` (same checkpoint)

The replay was run from the case's Regression test section after the polish
merge, so it records its checkpoint
(`nvidia/gr00t17-lerobot-libero_10-640` at `5ee08ab`). Verdict: **still
fails**.
- The minimal scene failed again (4 failures).
- The reference passed 5 of 5.

US$0.37.

## Spend

| Item | Cost |
| --- | --- |
| Run 1 and its replay | US$1.25 (of US$4 approved) |
| Run 2 and its replay | US$2.62 (of US$4.30 approved) |
| **Showcase total** | **US$3.87** |

These are ledger estimates; they still need reconciling against the Nebius
bill.
