# ADR 0024: M5D Tavily research context

**Status:** Accepted by Jethro on October 11, 2026.

## Problem

After Faultline confirms and reduces a failure, the engineer has measured
evidence and a Nemotron interpretation, but no pointer to public work on the
same kind of failure (for example, VLA sensitivity to camera occlusion). M5D
adds that context without letting it be mistaken for evidence.

## Decisions

1. **Trigger: a CLI step that writes an immutable research record.**
   `scripts/research_case.py` calls Tavily (and, separately, Nemotron) for a
   registered case and stores a content-addressed record beside the case's
   explanation reports. The viewer only reads and displays it; refreshing the
   viewer never calls a provider. Rejected: a live viewer button (makes the
   viewer hold a key and stop being read-only) and a search inside the
   Serverless job (key in the cloud, billed GPU time, not re-runnable).
2. **Queries: fixed templates over allowlisted descriptors.** Two or three
   deterministic queries built from the v2 evidence packet and fixed product
   constants: model family, LIBERO suite and task wording, perturbation family,
   reduced region in words and approximate area, failure type. No recordings,
   logs, paths, run or resource IDs, or dataset content leave the machine.
   Rejected for now: Nemotron-written queries (less auditable and testable).
3. **Display: a source-cited Nemotron summary.** Nemotron receives the
   deterministic case facts and the retrieved snippets and writes a short
   related-work note. Every entry must cite retrieved source IDs; the validator
   rejects uncited entries, unknown IDs and URLs that were not retrieved. The
   viewer shows it in a separate panel labelled as public context, not
   evidence. Retrieved text is untrusted data: length-capped, never executed or
   rendered as HTML.
4. **Caps.** Tavily: `basic` depth, at most 3 queries per search run,
   `max_results` 5, and at most **50 credits** for all of M5D (free plan, 1,000
   credits per month). Nemotron: at most **US$0.05**, as five labelled attempts
   with exclusive US$0.01 reservations. Cached results are reused unless
   `--refresh` is passed, and a refresh still counts against the credit cap.

## Claim boundary

Retrieved sources are context and hypotheses for the engineer. They are not a
failure oracle, do not prove a cause, and do not change any measured result.

## Prize rule

The Tavily call is a normal step of the diagnose workflow
(find → confirm → reduce → explain → research), not a development-only search.

## Reversibility

Fully reversible: new modules, a new record directory and a new viewer panel;
no change to search, reduction or the evidence packet.
