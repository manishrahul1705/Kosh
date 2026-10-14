# Canonical Kosh Demonstration Numbers

Deterministic simulation numbers generated from seed 42 with as-of date `2026-10-13` for **Meenakshi Precision Components**.

## 1. Baseline Cash Forecast & Alert

- **Forecast Run ID**: 1
- **Horizon**: 13 weeks, 2000 paths, seed 42
- **Cash Buffer**: ₹1,000,000.00 (100,000,000 paise)
- **Critical Alert**: Week 6
- **Alert Week Shortfall Probability**: 79.95%
- **Expected Shortfall**: ₹511,372.96 (51,137,296 paise)
- **Peak Expected Shortfall**: ₹587,748.92 (58,774,892 paise)

### Pre-intervention Weekly Probability Below Buffer

| Week | P10 Balance (₹) | P50 Balance (₹) | Prob Below Buffer | Expected Shortfall (₹) |
| :--- | :--- | :--- | :--- | :--- |
| W1 | ₹2,894,203.42 | ₹3,335,852.42 | 0.00% | ₹0.00 |
| W2 | ₹2,447,039.68 | ₹2,486,235.68 | 0.00% | ₹0.00 |
| W3 | ₹1,333,616.31 | ₹1,727,003.31 | 3.45% | ₹2,009.61 |
| W4 | ₹1,269,107.94 | ₹2,006,526.94 | 4.25% | ₹8,157.37 |
| W5 | ₹2,765,726.94 | ₹2,765,726.94 | 0.00% | ₹0.00 |
| W6 | ₹-129,026.17 | ₹631,761.20 | 79.95% | ₹511,372.96 |
| W7 | ₹-628,963.91 | ₹710,365.11 | 60.50% | ₹587,748.92 |
| W8 | ₹-801,491.53 | ₹1,441,584.86 | 41.20% | ₹484,513.70 |
| W9 | ₹1,380,836.49 | ₹3,239,086.45 | 6.10% | ₹44,592.89 |
| W10 | ₹1,608,130.94 | ₹3,850,286.64 | 5.20% | ₹41,291.01 |
| W11 | ₹1,367,336.51 | ₹3,914,795.96 | 6.95% | ₹64,293.44 |
| W12 | ₹359,103.71 | ₹2,993,968.90 | 16.30% | ₹195,250.04 |
| W13 | ₹196,271.17 | ₹3,208,060.08 | 16.80% | ₹221,762.79 |

## 2. Financing Plan (Target Probability <= 20%)

- **Plan ID**: 1
- **Overall Plan Status**: VALID
- **Guaranteed Plan Status**: VALID
- **Guaranteed Total Cost**: ₹10,242.92 (1,024,292 paise)
- **Expected Plan Total Cost (with Collections)**: ₹10,242.92 (1,024,292 paise)
- **NBFC Unsecured Loan Comparison Baseline Cost**: ₹64,677.54 (6,467,754 paise)
- **Calculated Savings vs NBFC Baseline**: ₹54,434.62 (84.2%)

### Executed Plan Lines

| Product | Scope | Amount (₹) | Week | Days | Cost (₹) | Effective Annual Rate | Tier |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| COLLECTIONS_PUSH | Invoice 378 | ₹197,897.00 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 379 | ₹198,442.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 381 | ₹215,531.00 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 383 | ₹368,709.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 384 | ₹195,933.00 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 385 | ₹200,843.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 386 | ₹185,262.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 387 | ₹208,504.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 388 | ₹196,693.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 389 | ₹217,734.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 390 | ₹216,298.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 391 | ₹203,301.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 392 | ₹214,339.00 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| COLLECTIONS_PUSH | Invoice 393 | ₹220,824.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| TREDS_INVOICE_DISCOUNTING | Invoice 395 | ₹935,836.09 | W1 | 47 | ₹10,242.92 | 8.59% | T3 |

## 3. Stage 4 Execution & Reforecast

- **Reminders Dispatched (Outbox)**: 14 collections reminders queued/sent (zero monetary cash fabricated).
- **Sandbox Ledger Postings**: 1 posting(s).
  - **TREDS_SETTLEMENT** (SANDBOX): Net cash proceeds of ₹925,593.17 posted on `2026-10-16`; receivable reduction ₹935,836.09.

- **Post-Execution Reforecast Run ID**: 16
- **Post-Execution Week 6 Shortfall Probability**: 19.35% (Target: <= 20.00%)
- **Post-Execution Open Cash Alert**: None (Alert fully resolved)

### Post-Execution Weekly Probability Below Buffer

| Week | P10 Balance (₹) | P50 Balance (₹) | Prob Below Buffer |
| :--- | :--- | :--- | :--- |
| W1 | ₹3,819,796.59 | ₹4,261,445.59 | 0.00% |
| W2 | ₹3,372,632.85 | ₹3,411,828.85 | 0.00% |
| W3 | ₹2,259,209.48 | ₹2,652,596.48 | 0.00% |
| W4 | ₹2,194,701.11 | ₹2,932,120.11 | 0.00% |
| W5 | ₹3,691,320.11 | ₹3,691,320.11 | 0.00% |
| W6 | ₹796,567.00 | ₹1,557,354.37 | 19.35% |
| W7 | ₹296,629.26 | ₹1,635,958.28 | 30.70% |
| W8 | ₹1,952.48 | ₹1,892,092.71 | 26.15% |
| W9 | ₹1,370,593.57 | ₹3,228,843.53 | 6.20% |
| W10 | ₹1,597,888.02 | ₹3,840,043.72 | 5.20% |
| W11 | ₹1,357,093.59 | ₹3,904,553.04 | 6.95% |
| W12 | ₹348,860.79 | ₹2,983,725.98 | 16.45% |
| W13 | ₹186,028.25 | ₹3,197,817.16 | 16.90% |
