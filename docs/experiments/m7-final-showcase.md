# M7: final showcase runs (October 19, 2026)

**Status:** in progress.

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

The start passed untouched, so the run took the probe route.
