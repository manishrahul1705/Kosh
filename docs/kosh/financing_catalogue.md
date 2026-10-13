# Financing catalogue

The catalogue is versioned product data. Provider labels, rates, fees, tenors and arrival speeds are illustrative assumptions, never paid placement. Scheme criteria include dated source blocks; entries marked `verified: false` must be verified before relying on them. Results are deterministic, include failed and review-required options, and never execute financing actions.

Cost ranking uses effective annual cost. Collections and supplier-term levers carry relationship-risk labels rather than invented interest. GeM Sahay stays REVIEW_REQUIRED: required evidence is missing and product terms have not been verified against a current primary source.


## Comparable costs

Every option quotes amount in paise, calendar tenor days, absolute interest plus fee,
net proceeds and effective annual rate. Collections and supplier terms have zero
monetary cost, with relationship risk retained. Loans/OD use annual IRR on proceeds
net of the upfront fee and principal plus simple interest repaid at tenor end.
Discounting uses (discount + fee) / net proceeds * 365 / days.

No primary source in this offline catalogue supports the former TReDS 10.5% rate
or 1% fee. We use a **clearly illustrative CPSE TReDS discount rate of 8.5% p.a.**
(within the requested illustrative 7?10% range), 90 days, zero processing fee.
This is a modelling assumption, not a verified lender quote; source of the numeric
assumption is the Stage 3.1 specification, not a primary publication. No external
verification was performed. At 90 days the effective annual discount cost is
8.5% / (1 - 8.5% * 90 / 365) = **8.681964%** before integer-paise rounding.
Actual auction rate, fees and invoice maturity must be verified before execution.
PMMY source URL is https://www.mudra.org.in/; criteria dates record the supplied
Stage 3.1 rules, and verified=false explicitly preserves pending live verification.


## Plan cash-flow dates

The options table retains the **90-day quote basis** for comparison. Plan lines
use dated cash flows: discounting runs from the funding business day to the
recorded invoice maturity (and is unavailable if maturity is at/before funding).
OD and loans use the actual days between funding and the planned bullet repayment
date. The default repayment assumption is the catalogue's 90-day bullet term;
an explicitly chosen repayment date overrides that assumption. Every plan line
records both dates, actual days and the repayment assumption. The same-target
NBFC comparison follows the same rules and forecasts the actual repayments.


## Already-sanctioned OD

BANK_OD_DRAWDOWN has **no upfront fee per drawdown**. Any annual sanction or
renewal fee is already sunk, so incremental draw cost is principal * illustrative
12% annual interest * actual days drawn / 365. The options quote is still 90 days;
plan interest and annual IRR follow the recorded funding and repayment dates.


## Allocation and forecast proof

The optional linprog path remains optional; SciPy is not added as a dependency.
The least-cost allocation is exact for **one net-cash constraint and independent
caps**. Cheapest-first greedy solves that fractional allocation when SciPy is
absent. The LP receives dimensionless allocation fractions; monetary values and
rounding remain integer paise and Decimal. Shared invoice capacity is reserved
for zero-cost collections before discounting, so a receivable is not funded twice.
This allocation result is not a general chance-constrained optimisation proof.
Safety is separately verified by the **same-seed forecast**: alert-week probability
must be at most the chosen target, and every horizon week must remain strictly
below the alert threshold. The target defaults to 0.20; the alert defaults to 0.50.
The capacity loop and paid-amount trimming recheck those conditions. A failure is
INSUFFICIENT, not a valid plan. The NBFC baseline is forecast-verified at that same
target, using the same free collections, timing, fees and repayment assumptions;
an unattainable NBFC baseline is labelled INSUFFICIENT, without invented savings.

Operational collections/supplier levers have no financing tenor or repayment
obligation: plan days are 0 and repayment_date is null. Their options retain the
90-day quote display basis for the consistent table, with zero monetary cost.
