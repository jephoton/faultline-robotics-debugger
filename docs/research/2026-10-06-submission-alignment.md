# Submission alignment — October 6, 2026

Generated review of the [official rules](https://nebiusglobalaihackathon.devpost.com/rules),
[overview/judging criteria](https://nebiusglobalaihackathon.devpost.com/), and
[organizer submission advice](https://nebiusglobalaihackathon.devpost.com/updates/46205-how-to-build-a-winning-project).
Recheck before submission; this is not organizer approval.

## Requirement check

The rules require a working application, an NVIDIA open-source model and
Nebius runtime use. They define the latter as a Token Factory inference call
or AI Cloud execution, specifically naming Serverless Jobs, Endpoints and
DevPods. Do not assume our VM alone satisfies that wording. A genuine M5C
Token Factory inference path is the shortest planned compliance route; a
catalog GET is not inference. The Physical AI text also explicitly directs
simulation/policy evaluation toward Serverless Jobs. Whether VM evaluation
plus Token Factory suffices for that track remains an organizer clarification,
not a reason to silently migrate the infrastructure.

Physical AI without hardware is explicitly allowed: include at least one
minute showing key application modules operating. Submit an English
description, public open-source code with setup instructions, required tool
feedback, and a publicly visible YouTube video shorter than three minutes.
The track has a demo-URL exemption, but judge access/testing still needs a
usable build. Preserve access through December 15. Deadline: October 30,
10:00 PDT / October 31, 01:00 Singapore.

## Our evidence and remaining work

| Area | Verified position | Remaining gate |
| --- | --- | --- |
| NVIDIA robotics use | GR00T ran closed-loop simulated manipulation on Nebius GPU compute | Name actual model/checkpoint and distinguish missing historical pins from future verified pins |
| Nebius inference | Reviewed client/CLI/viewer integrated; one real request returned no valid interpretation | Separately approved bounded repair/second attempt; useful grounded report and human review |
| Working product | M5A inspection/export/import and paired evidence viewer completed | External restored-state policy replay and M5C explanation path remain unfinished |
| Public build | Authenticated GitHub check confirms repository is PRIVATE and Apache-2.0 is detected; setup instructions and automated tests exist | Clean-room judge smoke test, artifact availability, dependency/asset rights and secret/history audit; explicit approval before making repository public |
| Feedback | Root FEEDBACK.md captures actual cloud/model friction | Add actual Token Factory generation experience, reconcile costs, get user first-hand feedback |
| Video/submission | Roadmap already includes pitch and public-repo audit | Final name, narrated demo, public YouTube upload and Devpost fields |

## Judging alignment (all four criteria are equally weighted)

**Technological implementation:** Show actual GR00T execution and real
Nemotron use, not a provider logo or mocked response. Nemotron interprets a
bounded evidence packet; it does not determine task success, certify safety,
or claim to have watched videos. Keep credentials outside the browser/repo.

**Design:** The product story is one coherent case journey: inspect a robot
failure, see nominal versus perturbed evidence, follow its reduction lineage,
read grounded interpretation, and take away a replay/regression recipe.
CLI mutations with a read-only viewer are acceptable product boundaries if
the documented walkthrough is frictionless. M5B is needed to demonstrate
that an externally supplied episode can actually enter this workflow.

**Potential impact:** Target robotics policy/evaluation engineers who need
smaller reproducible regressions rather than another full evaluation sweep.
Demonstrate one exact task and perturbation family honestly. Do not claim
universal artifact import, all failures, real-world robot safety, or a proven
globally minimal mask.

**Quality of idea:** Position the integrated find → confirm → reduce → replay
loop as the contribution. Occlusion and parallel evaluation already exist.
The measured base M3 throughput result is supporting evidence, not the core
pitch or proof of end-to-end diagnostic speedup/cost savings. Expanded M3
stays frozen; M6 broader validation remains pending.

## Proposed name discussion (not a rename)

- **Faultline** — memorable; captures the boundary where robot behaviour fails.
  Suggested descriptor: “Turn robot failures into replayable tests.” Recommended.
- **Replay Lab** — immediately understandable; less distinctive.
- **Blackbox** — conveys investigation, but is broad and may imply less
  transparency than our evidence-first interface.

These names have not been checked for trademark, domain, package or product
availability. Jethro chooses before branding, repository renaming or publication.
Jethro prefers **Faultline**, kept in view for now. This is not final branding,
repository renaming or publication approval; naming does not block M5.

The acquired external HDF5's license/attribution discrepancy remains unresolved.
Do not redistribute it in the public judge package until rights are established;
prefer documented authorized acquisition or separately cleared demonstration
artifacts. A repository code license does not license third-party datasets/models.
