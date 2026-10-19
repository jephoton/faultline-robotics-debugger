# Billing reconciliation — partial evidence

Status: **period totals recorded; lifetime/per-run reconciliation incomplete**.
The project owner supplied AI Cloud and Token Factory consumption screenshots, plus a
date selector showing **September 19–October 19, 2026**, on October 20.
The project owner confirmed this is the **only AI Cloud account used for Faultline**;
the earlier planned account split was not actual usage. The crops do not
show project filters or an ISO currency code. These are console usage views,
not settled invoices or evidence for dates outside the selected window.
Do not commit original screenshots or private billing/account details here.

## Values visible in the supplied view

Amounts below preserve the displayed dollar sign. The supplied date selector
provides the reporting window; project-filter scope and currency code are
not independently visible. Treat run-level estimates separately.

### AI Cloud

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

### Token Factory

Usage is displayed in millions of tokens, rounded by the console. For example,
0.07 in that column is approximately 70,000 tokens, not an exact token count.

| Model/direction | Displayed usage (million tokens) | Displayed cost |
| --- | --- | --- |
| Nemotron 3 Ultra input | 0.07 | $0.07 |
| Nemotron 3 Ultra output | 0.01 | $0.04 |
| Nemotron 3 Nano input | 0.06 | < $0.01 |
| Nemotron 3 Nano output | 0.02 | < $0.01 |
| Nemotron 3 Super input | < 0.01 | < $0.01 |
| Nemotron 3 Super output | < 0.01 | < $0.01 |
| **Subtotal** | | **$0.12** |
| **VAT** | | **$0.01** |
| **Total** | | **$0.13** |

Do not replace the '< $0.01' entries with zero or infer exact per-call prices
from rounded aggregate usage.

### Combined supplied views

| Service | Before VAT | VAT | Including VAT |
| --- | --- | --- | --- |
| AI Cloud | $38.57 | $3.47 | $42.04 |
| Token Factory | $0.12 | $0.01 | $0.13 |
| **Arithmetic sum** | **$38.69** | **$3.48** | **$42.17** |

This is the sum of the two supplied service views for the selected period,
not an independently exported account grand total or a lifetime project total.

## What this does and does not establish

- This is a concrete provider-displayed usage total for the selected view,
  replacing guesswork about that view only.
- The $10.34 disk line is visible development/storage cost, not robot runtime.
  Keep storage and VAT separate when comparing with GPU-time estimates.
- It does **not** independently validate a particular diagnosis's estimate,
  the US$3.87 showcase subtotal or a lifetime total. Token Factory's supplied
  aggregate is now recorded, but individual calls remain unmatched.
- The project owner also reported **$0.82 remaining**, without a service/account/date
  scope. A remaining balance is not consumption and is not an allowance for
  new paid work. Do not reverse-engineer spend from assumed top-ups.

## Inputs still needed

1. If a lifetime cost is needed, account for project usage before September 19
   and after October 19, or confirm there was none. The project began before
   this window; do not assume the selected month covers everything.
2. Confirm currency/project filters if publishing an account-wide total.
   No second AI Cloud account is needed; the project owner confirmed only one was used.
3. Where practical, use a redacted usage breakdown/export to map cloud time
   to run dates, including setup/failed/idle development runs, storage and tax.

Use the scoped service totals in README/feedback/Devpost, not a claimed
lifetime total, while those questions remain. If exact
per-run reconciliation is impossible, present the confirmed scoped provider
total and label the per-run estimates separately, with the unmatched scope
explicit. No new provider API request or paid experiment is needed to record
this screenshot.
