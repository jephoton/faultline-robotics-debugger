# Nemotron feedback questionnaire — review draft

Draft answers, not submitted. The three ratings need the project owner's input.
The sign-in and GPU-capacity feedback below includes the approved first-hand notes.

## 1. Which models, and why those sizes/variants?

We used Nemotron 3 Ultra 550B-A55B for layout hypotheses, explanations and next
steps; Super 120B-A12B for instruction rewordings; and Nano 30B-A3B for earlier
research summaries. All ran through Token Factory. In our small comparisons,
Ultra made fewer explanation errors. Super kept the meaning in all ten checked
rewordings and varied the wording more than Ultra. Nano changed a target in one.

## 2. Output quality: rating and explanation

**Rating: [project owner to choose, 1–10].**

Ultra explained test results well, but none of the models was consistently
correct. Nano confused an applied change with a reverted one; Super inverted
a prediction. Some answers cited nonexistent evidence or claimed more than
the tests showed. Ultra also needed a retry. We check answers in code and do
not let the model decide whether a robot test failed.

## 3. Fine-tuning, prompting or out of the box?

No fine-tuning. We supplied instructions, test results and evidence IDs, and
requested JSON. Precomputing counts and describing each rerun in one sentence
helped. Code checks the fields, references and unsupported claims. Invalid
next-step answers get one retry with the rejection reason, then are hidden if
still invalid. Rewordings are checked for meaning before use.

## 4. Comparison with other models used for similar tasks

We compared Nano, Super and Ultra on the same project inputs, not against
other model families. Ultra was better at explanations; Super was better for
varied rewordings that kept the meaning. We cannot claim either outperforms
another provider's model on this task.

## 5. Most valuable Nebius capabilities and deployment details

Token Factory let us call Nemotron without running a model server. Its
OpenAI-compatible API made integration simple; token and latency reporting
helped compare calls. Separately, Serverless Jobs ran GR00T and LIBERO on one
L40S per Job. We used a private registry for the image, Object Storage for
videos/traces and a secret store for model access. Nemotron ran through Token
Factory, not on those L40S Jobs. We did not test Nemotron autoscaling.

## 6. Likelihood of recommending Nemotron on Nebius

**Rating: [project owner to choose, 1–10].**

Yes, for explanations and rewordings that an application checks before use.
The API was easy to use once we confirmed the endpoint and model name. I
would not use its answers alone to decide what caused a robot failure.

## 7. Inference experience versus previous cloud/local environments

**Rating: [project owner to choose, 1–10, based on actual prior experience].**

Token Factory saved us from setting up a Nemotron server. The documentation
had inconsistent endpoint/model examples. We did not run the same model
locally or on another cloud, so we cannot make a direct performance comparison.

The broader AI Cloud experience was more frustrating. The CLI sign-in expired
after about a day; twice a run stopped partway, once mid-Job, and I had to sign
in through the browser and resume. GPU availability was the biggest delay:
on October 13, four of nine L40S submissions found no machine after about
27 minutes of retries; another took 22 minutes to start. Waiting was not
billed. These were AI Cloud issues, not Token Factory inference failures.

## 8. Features or improvements that would help

- Token Factory: consistent endpoint/model examples, clearer output-token
  guidance, and easier matching of call usage to billed charges.
- AI Cloud: clearer guidance for unattended authentication and an explicit
  expired-session error instead of a generic timeout. Having to return and
  sign in repeatedly interrupted the work.
- GPU capacity: show an estimated wait or suggest an available alternative
  machine. Long retries without knowing whether a GPU would become available
  made short experiments take hours.

## 9. What we hope to see from the Nemotron team next

Fewer mistakes when reading test results: correct counts, correct descriptions
of which changes were applied, no invented evidence references, and no claims
of cause when the tests only show a repeated failure. Getting that reliability
in smaller models would let us use them for more of the explanations.

## Internal sources — do not paste as an extra answer

- [Model comparison and selection](../decisions/0030-nemotron-model-per-task.md).
- [Approved feedback](../../FEEDBACK.md) and
  [interaction history](../experiments/tool-feedback-history.md).
- [Recorded billing period](billing-reconciliation.md): Token Factory $0.13
  including VAT, September 19–October 19, 2026. This is not a lifetime total
  or an exact cost for each model task.

No new inference calls or provider access were needed to prepare these answers.
