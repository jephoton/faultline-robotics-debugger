# Billing reconciliation — partial evidence

Status: **incomplete**. Jethro supplied an AI Cloud consumption screenshot on
October 20. The crop does not show its date range, account/project filter,
currency code. Jethro subsequently confirmed this is the **only AI Cloud
account used for Faultline**; the earlier planned account split was not the
actual usage scope. It is a console
usage view, not evidence of a settled invoice or total project spend. Do not
commit the original screenshot or private billing/account details here.

## Values visible in the supplied view

Amounts below preserve the displayed dollar sign; confirm USD and scope
before using them as final submission costs.

| Category | Usage shown | Displayed cost |
| --- | --- | --- |
| H100 NVLink | 1.72 GPU hours | $7.73 |
| L40S GPU | 11.60 GPU hours | $15.66 |
| L40S CPU | 185.57 vCPU hours | $2.23 |
| L40S RAM | 742.29 GiB hours | $2.38 |
| Network SSD disk | 106,334.82 GiB hours | $10.34 |
| Network SSD snapshot | 212.54 GiB hours | $0.02 |
| **Compute category total** | | **$38.35** |
| Object Storage | Collapsed in screenshot | $0.23 |
| Virtual Networks | Collapsed in screenshot | $0.00 |
| **Subtotal** | | **$38.57** |
| **VAT** | | **$3.47** |
| **Total** | | **$42.04** |

Displayed rounded line items differ from their displayed category/subtotal by
one cent. Retain the console's aggregates; do not silently force the rows to
sum or infer a billing error without underlying usage/export precision.

## What this does and does not establish

- This is a concrete provider-displayed usage total for the selected view,
  replacing guesswork about that view only.
- The $10.34 disk line is visible development/storage cost, not robot runtime.
  Keep storage and VAT separate when comparing with GPU-time estimates.
- It does **not** independently validate a particular diagnosis's estimate,
  the US$3.87 showcase subtotal, Token Factory charges or a lifetime total.
- Jethro also reported **$0.82 remaining**, without a service/account/date
  scope. A remaining balance is not consumption and is not an allowance for
  new paid work. Do not reverse-engineer spend from assumed top-ups.

## Inputs still needed

1. Confirm the screenshot's date range, currency and project filters, without
   posting account identifiers.
2. Provide other periods for this same AI Cloud account if the screenshot
   does not cover the whole project. No second AI Cloud account is needed;
   Jethro confirmed only one was used.
3. Provide Token Factory usage charges and date range separately. Its credit
   balance/top-ups do not establish inference usage.
4. Where practical, use a redacted usage breakdown/export to map cloud time
   to run dates, including setup/failed/idle development runs, storage and tax.

Only then update final total-cost claims in README/feedback/Devpost. If exact
per-run reconciliation is impossible, present the confirmed scoped provider
total and label the per-run estimates separately, with the unmatched scope
explicit. No new provider API request or paid experiment is needed to record
this screenshot.
