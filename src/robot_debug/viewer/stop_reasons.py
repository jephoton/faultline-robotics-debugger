"""Plain-language text for the reasons a run stops (ADR 0033).

One table, shared by the live run page and the case pages, so a stop reason reads the same wherever it
appears. The reasons are the orchestrator's ``StopRun`` reasons and the summaries' own stop reasons; the
page shows the sentence, never the raw reason or the exception text behind it.
"""

from __future__ import annotations

from typing import Dict, Optional

STOP_TEXTS: Dict[str, str] = {
    "budget_exhausted": "Stopped at the candidate budget; this is the smallest cause found so far.",
    "nominal_controls_failed": "The unperturbed policy did not pass reliably, so no disturbance can be judged.",
    "no_reproducible_failure": "No failure repeated 4 of 5 times.",
    "no_reference": "No nearby benchmark start passed reliably.",
    "import_invalid": "The imported start file was not valid.",
    "import_mismatch": "The imported start did not match the task's scene.",
    "no_faithful_failure": "The imported start did not fail reliably.",
    "original_mismatch": "The original wording did not match the task.",
    "capacity_unavailable": "No GPU became available after six submissions.",
    "spend_cap": "The next Job could exceed the spend cap.",
    "max_hours": "The hour limit was reached.",
    "stopped_by_user": "Stopped from the control panel or `faultline stop`.",
    "backend_error": "The cloud call failed; resume to re-attach.",
    "auth_expired": "Your Nebius sign-in expired. Sign in, then resume.",
    "control_not_passing": ("The original wording did not pass both control attempts, so a failing rewording "
                            "cannot be attributed to the wording."),
    "paraphrase_failed": "Nemotron could not write the rewordings. Resume to try again.",
    "llm_required": "Rewordings need Nemotron; run again with Nemotron on.",
    "original_unknown": "The task's own wording is not known; give it in the spec to probe its rewordings.",
    "process_ended": ("The run's process ended before it finished (for example the control panel or this computer "
                      "was shut down). Resume re-attaches to any Job it left running without paying for it twice."),
}

# A stop that is a clean negative finding is a result, not a problem: everything else needs a look (amber).
NOT_ATTENTION = frozenset({"no_reproducible_failure"})


def stop_text(reason: Optional[str], detail: Optional[str] = None) -> Optional[str]:
    """The sentence for a stop ``reason`` (``None`` for no reason). ``backend_error`` whose detail says the
    sign-in expired reads as the sign-in problem it is, because that is the action the person must take."""

    if not reason:
        return None
    if reason == "backend_error" and detail and "sign-in has expired" in detail:
        reason = "auth_expired"
    return STOP_TEXTS.get(reason, "Stopped: {}.".format(reason))


def needs_attention(reason: Optional[str]) -> bool:
    """Whether a run that stopped for ``reason`` should be marked amber."""

    return bool(reason) and reason not in NOT_ATTENTION
