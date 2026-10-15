# ADR 0031: `faultline diagnose` — one command for a whole diagnosis

**Status:** Accepted by Jethro on October 14, 2026 (M7a step 2 checkpoint).

## Problem

Mode 1 worked on October 13 only because the coordinator hand-ran scratchpad
scripts: bucket and read-only key setup, image checks, submission, the
watchdog, a capacity resubmitter, per-run downloads, local Nemotron planning
between Jobs, a continuation run, report, case and explanation, and identity
revocation. A user cannot do that. ADR 0027 asks for one command.

## Decision

1. **Scope: the full pipeline, orchestrated locally.** `faultline diagnose
   SPEC.yaml` runs mode 1 (optional screen, automatic choice of the failing
   start, Nemotron planning, reduction, automatic continuation while the
   result is not entity-minimal and the spend cap allows, report, case,
   explanation) or mode 2 (one audit Job, report, case) as several Jobs driven
   from the user's machine. The Token Factory key never enters a Job.
2. **Nebius interface: wrap the official `nebius` CLI** from Python (on PATH,
   or inside WSL on Windows), reusing the proven commands. No new SDK.
3. **Image distribution: build-from-Dockerfile for everyone, plus a public
   GHCR image.** `faultline image build/push` targets the user's own
   registry. Publishing Faultline's image publicly on GHCR is accepted in
   principle; the actual publication still needs a licence check of the
   third-party packages in the image and Jethro's explicit go at that time.
   Model weights are never in the image (downloaded at run time with the
   user's Hugging Face token).
4. **Startup cut (ADR 0029 A): skipped for now.** Jobs keep downloading the
   pinned weights from Hugging Face (about 6 minutes). Revisit only if time
   allows after the UI and breadth work.

**Defaults accepted with it:** interactive Nebius CLI sign-in (service
accounts later); a required spend cap and hard deadline in every spec (the
command refuses to run without them); a local GPU backend built but labelled
untested on GPU (the development machine has no suitable GPU).

## Consequences

- One results bucket per diagnosis (not per Job) and one reusable read
  identity per project keep the tenant under its bucket-policy quota; per-run
  access keys are deleted at the end.
- The capacity resubmitter, deadline guard and watchdog become product code
  with tests instead of scratchpad scripts.
- The experiment-named Job modes stay for replaying recorded evidence; the
  scenario and audit modes are driven by the spec.

## Implementation notes (October 15)

- An independent review before the first live run found seven defects (a
  setup crash, Jobs left running after Ctrl-C during submit, a worst case that
  the fixed one-hour provider timeout could exceed, unbounded waiting, and a
  possible second `job create`); all were fixed with tests, including an
  end-to-end mode-1 test through the real Nebius backend and a fake CLI.
- **Worst case is now a real upper bound:** provider timeout =
  ceil((deadline + 600 s) / 60) x 60; reservation = (timeout + 240 s start
  allowance) x hourly rate. The watchdog cancels at deadline + 300 s and the
  provider stops the Job at the timeout even if the laptop sleeps.
- `scenario.start` screens a configurable reference pool (default starts
  0-19) instead of 0-49.
- Every finished diagnosis or replay saves `replay-inputs.json`, so a case can
  be replayed later from the diagnoses index.

