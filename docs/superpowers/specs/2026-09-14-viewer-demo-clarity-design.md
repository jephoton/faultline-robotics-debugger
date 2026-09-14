# Viewer Demo Clarity Design

**Status:** Approved for implementation on 2026-09-14.

## Purpose

Make the artifact viewer understandable to a first-time hackathon judge within
roughly 15 seconds. The central story is a controlled comparison: select a
nominal episode, compare it with a fault-injected episode, then verify the
behavioral difference using synchronized video, outcome metadata, and trace
evidence.

This is an MVP usability pass. It does not add new artifact formats, APIs,
charts, annotations, persistence, or cloud behavior.

## Experience hierarchy

The interface presents one three-step path:

1. **Choose evidence.** The run rail makes outcome, nominal/fault status, mask
   severity, and step count scannable. The selected run is visually obvious.
2. **Compare behavior.** The center gives a one-sentence instruction and frames
   the selected videos as reference and investigation evidence. Existing
   selectors still permit any pair.
3. **Explain the result.** A conclusion line summarizes the selected pair, such
   as `SUCCESS → FAILURE at 14.06% centered occlusion`. Diagnostics and the
   timeline supply the evidence behind that statement.

## Visual language

Retain the dark forensic-console identity, offline system fonts, square edges,
thin borders, and compact technical typography. Increase video prominence,
reduce competition from metadata, and add spacing around the comparison.

Outcome meaning must remain consistent throughout the interface:

- success: green;
- robot task failure: red;
- episode timeout: amber;
- infrastructure error: muted violet, accompanied by wording that the policy
  was not evaluated.

The primary selection uses a cyan accent. Color is supplementary: every state
also has a text label.

## Components and behavior

Add a compact guide above the evidence area with the three actions: select a
reference, compare a perturbed run, inspect the outcome and trace. It should be
useful during a live demo without becoming a tutorial overlay.

Run buttons receive a visible outcome badge, a nominal or mask-severity label,
and a selected state. The current filter and episode selection behavior remain
unchanged.

The two evidence channels use contextual role text. A run with no enabled
perturbation is labelled `REFERENCE / NOMINAL`; a run with a perturbation is
labelled `INVESTIGATION / PERTURBED`. These are presentation labels inferred
from existing metadata, not restrictions on which episodes can be paired.

The conclusion line is deterministic and cautious. It reports both selected
outcomes and includes perturbation area only when one selected episode has a
rectangular perturbation. It must not claim causation or divergence timing.

Rename the transport labels to `Play both`, `Pause both`, and `Restart both`.
Show whether linked playback is active. Keep timestamp alignment and the note
that trajectories are not assumed identical.

## Loading and incomplete evidence

- Initial catalog load: `Loading experiment evidence…`.
- Empty catalog: explain that experiment outputs must be placed in the selected
  `artifacts/` directory.
- One episode: display it and state that another episode enables comparison.
- Missing video or trace: preserve all other evidence and label the missing
  medium explicitly.
- Catalog warning: display it below the workflow without hiding valid runs.
- Infrastructure error: state that the robot policy was not evaluated.

## Responsive and accessible behavior

At desktop width, preserve the run rail, paired videos, and diagnostic column.
At narrow widths, use a compact episode selection area, stack video channels,
and place diagnostics after the timeline. Maintain semantic landmarks,
keyboard order, visible focus rings, live regions, text alternatives for trace
events, and reduced-motion behavior.

## Acceptance criteria

- A first-time viewer can identify the nominal run, perturbed run, and result
  without opening raw JSON.
- Outcome colors and labels are consistent in the rail and conclusion.
- The conclusion is derived only from selected episode metadata.
- Empty, loading, single-run, missing-media, and infrastructure-error states
  remain usable.
- Existing linked playback, polling, filtering, diagnostics, and trace behavior
  still works.
- No request leaves the loopback viewer and no artifact is modified.
- The real baseline and global-occlusion evidence pass the browser demo check.

