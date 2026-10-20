# Nemotron feedback questionnaire — review draft

Prepared from recorded project observations, not submitted. The project owner
must choose the three subjective ratings and approve the wording. The existing
approved first-hand notes remain approved; this questionnaire adds form-specific
answers, not a replacement account of the experience.

## 1. Which models, and why those sizes/variants?

We used Nemotron 3 Nano 30B-A3B, Super 120B-A12B and Ultra 550B-A55B through
Nebius Token Factory. We chose by task rather than using the largest model
everywhere. In small comparisons on stored inputs, Ultra was the most reliable
for explaining scenario evidence and is used for layout hypotheses,
explanations and suggested next steps. Super produced more varied instruction
paraphrases while preserving the target objects: all ten checked paraphrases
kept their meaning, whereas Nano changed a target in one and Ultra's wording
was too similar. Nano handled earlier short research summaries. These were
small task-specific comparisons, not a general model benchmark.

## 2. Output quality: rating and explanation

**Rating: [project owner to choose, 1–10].**

Ultra could turn measured robot-test evidence into useful explanations, and
Super generated usable instruction variations. Reliability still required
guardrails. Nano once described an applied scene change as reverted; Super
inverted a prediction in an explanation; outputs sometimes cited nonexistent
evidence or used wording stronger than the tests justified. Even Ultra needed
a repair attempt on a later next-steps response. We therefore precompute facts,
validate structure and citations, and keep model hypotheses separate from
simulator outcomes. We did not assess multilingual performance.

## 3. Fine-tuning, prompting or out of the box?

No fine-tuning. We prompt-engineered the hosted models with task-specific
instructions, measured evidence packets, explicit evidence IDs and constrained
JSON output requirements. For explanations, one plain sentence per rerun and
precomputed shrink history helped prevent misreading. Code validates required
fields, citations and unsupported claims. A next-steps response can receive
one repair attempt with the rejection reason; if it still fails, it is not
shown. Instruction variations also undergo a meaning check before use. We
adjusted output budgets and used the hosted thinking control where appropriate.

## 4. Comparison with other models used for similar tasks

Our controlled comparison was between Nemotron variants, not against another
model family. On the same stored explanation inputs, Ultra preserved the
checked facts where Nano or Super made factual or formatting errors. Super
was a better fit for varied, meaning-preserving paraphrases. Nano was adequate
for an earlier short summary task. We have not measured whether Nemotron
outperforms another vendor's model on robotics diagnosis, and coding-assistant
use during development is not an equivalent comparison.

## 5. Most valuable Nebius capabilities and deployment details

Token Factory's OpenAI-compatible API let the local Faultline backend call
Nemotron without provisioning a separate model-serving GPU. Token usage and
latency reporting helped us track individual calls and compare variants.
Hosted inference supported layout-hypothesis ranking, instruction generation
and report assistance; we have not measured diagnostic speed gains from it.

Separately, Nebius AI Cloud Serverless Jobs ran the GR00T robot policy and
LIBERO simulations on one NVIDIA L40S GPU per Job. A private registry supplied
the simulator image, Object Storage held videos and traces, and a secret store
injected the Hugging Face token. Nemotron was served by Token Factory, **not**
by those L40S Jobs. We did not deploy a Nemotron Endpoint, fine-tune it or test
autoscaling Nemotron infrastructure ourselves.

## 6. Likelihood of recommending Nemotron on Nebius

**Rating: [project owner to choose, 1–10].**

I would recommend it for human-reviewed hypotheses, structured explanations
and wording generation. API integration was straightforward once the model
identifier and endpoint were confirmed, and using different sizes for different
tasks was useful. I would not treat generated diagnoses as ground truth:
robotics claims still need explicit evidence checks and simulator reruns.

## 7. Inference experience versus previous cloud/local environments

**Rating: [project owner to choose, 1–10, based on actual prior experience].**

For this project, hosted Token Factory inference avoided operating our own
Nemotron model server. The main onboarding friction was that API credentials
were separate from the AI Cloud CLI session, and cookbook/quickstart model
identifiers and endpoint examples differed. Usage reporting and the thinking
control were helpful. We did not run an equivalent Nemotron workload locally
or on another cloud, so this is not a controlled latency, cost or quality
comparison with those environments.

## 8. Features or improvements that would help

Consistent copyable endpoint/model identifiers across the catalog, quickstart
and cookbook would shorten onboarding. Clearer guidance on thinking mode,
output-budget sizing and structured-output validation would help applications
that need short, evidence-bound answers. Easier matching of per-call usage
records to billed charges would also help us reconcile estimates.

For the broader AI Cloud workflow, clearer expired-authentication errors and
capacity estimates or alternative GPU-preset suggestions would reduce time
spent waiting and recovering. These were cloud-orchestration issues, not
Nemotron output-quality failures.

## 9. What we hope to see from the Nemotron team next

Better reliability on evidence-grounded structured tasks: distinguish an
observed result from a hypothesis, preserve exact counts and applied/reverted
state, and cite only supplied evidence. We would also value smaller models
that retain this reliability for low-cost explanations, and published
evaluations for scientific or robotics evidence interpretation. For Faultline,
faithful uncertainty is more useful than a confident explanation unsupported
by the reruns.

## Internal sources — do not paste as an extra answer

- [Model comparison and selection](../decisions/0030-nemotron-model-per-task.md).
- [Approved feedback](../../FEEDBACK.md) and
  [interaction history](../experiments/tool-feedback-history.md).
- [Recorded billing period](billing-reconciliation.md): Token Factory $0.13
  including VAT, September 19–October 19, 2026. This is not a lifetime total
  or an exact cost for each model task.

No new inference calls or provider access were needed to prepare these answers.
