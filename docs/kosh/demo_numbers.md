# Canonical Kosh Demonstration Numbers

Deterministic simulation numbers generated from seed 42 with as-of date `2026-10-13` for **Meenakshi Precision Components**.

## 1. Business Snapshot

- **Company Name**: Meenakshi Precision Components
- **As-Of Date**: `2026-10-13`
- **Latest Bank Balance**: ₹2,497,318.42 (249,731,842 paise)
- **Open Receivables**: ₹10,948,317.40 (1,094,831,740 paise)
- **Open Payables**: ₹3,803,973.22 (380,397,322 paise) *(verified only)*
- **Held for Review (Payables)**: ₹960,000.00 (96,000,000 paise) *(quarantined poisoned invoices POISON-001 & POISON-002)*
- **Cash Buffer Target**: ₹1,000,000.00 (100,000,000 paise)

## 2. Baseline Cash Forecast & Alert

- **Forecast Run ID**: 1
- **Horizon**: 13 weeks, 2000 Monte Carlo paths, deterministic seed 42
- **Critical Alert**: Week 6
- **Alert Week Shortfall Probability**: 79.95%
- **Expected Shortfall**: ₹511,372.96 (51,137,296 paise)
- **Peak Expected Shortfall**: ₹587,748.92 (58,774,892 paise)

### Pre-intervention Weekly Forecast Table

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

## 3. Financing Product Catalogue Evaluation

All 8 financing catalogue products evaluated deterministically against current entity facts, document evidence, and invoice criteria:

| Product ID | Product Name | Status | Eligible Scope / Invoices | Evaluation Reason |
| :--- | :--- | :--- | :--- | :--- |
| `BANK_OD_DRAWDOWN` | Bank OD drawdown | **MATCHED** | Entity facility | Criterion met. |
| `CGTMSE_BACKED_WC_LOAN` | CGTMSE-backed working capital loan | **REVIEW_REQUIRED** | Entity facility | Required business evidence is missing. |
| `COLLECTIONS_PUSH` | Collections push | **MATCHED** | 14/27 eligible | Matched scope: 14 invoices (Criterion met). Other invoice scopes shown separately. |
| `GEM_SAHAY_PO_FINANCE` | GeM Sahay PO finance | **REVIEW_REQUIRED** | Entity facility | Required business evidence is missing. |
| `MUDRA_LOAN` | MUDRA loan | **REVIEW_REQUIRED** | Entity facility | Required business evidence is missing. |
| `NBFC_UNSECURED_BUSINESS_LOAN` | Unsecured business loan | **MATCHED** | Entity facility | Criterion met. |
| `SUPPLIER_TERM_EXTENSION` | Supplier term extension | **REVIEW_REQUIRED** | 0/8 eligible | Required business evidence is missing. |
| `TREDS_INVOICE_DISCOUNTING` | TReDS invoice discounting | **MATCHED** | 1/27 eligible | Matched scope: Invoice 395 (Criterion met). Other invoice scopes shown separately. |

### Invoice Scope Breakdown for Multi-Scope Levers

- **`TREDS_INVOICE_DISCOUNTING`** (1/27 eligible):
  - **Matched Scope (1)**: Invoice 395 meets approved CPSE buyer, verified invoice, and tenor <= 90 days criteria.
  - **Other Invoice Scopes (26)**: 21 review required (buyer TReDS platform onboarding required); 5 not matched (tenor/ineligible).
- **`COLLECTIONS_PUSH`** (14/27 eligible):
  - **Matched Scopes (14)**: Invoices 378, 379, 381, 383, 393, 384, 385, 386, 387, 388, 389, 390, 391, 392 meet statutory reminder eligibility (overdue or due within 30 days).
  - **Other Invoice Scopes (13)**: 13 not matched (due > 30 days or not yet eligible).
- **`SUPPLIER_TERM_EXTENSION`** (0/8 eligible):
  - **Matched Scopes (0)**: None.
  - **Other Invoice Scopes (8)**: 8 payables in review (supplier payment term negotiation addendum required).

## 4. Financing Plan & Optimization

- **Plan ID**: 1
- **Target Probability**: &le; 20.00%
- **Target Scope**: `ALL_WEEKS` (every horizon week must meet target)
- **Overall Plan Status**: **VALID**
- **Guaranteed Plan Status**: **VALID**
- **Guaranteed Total Cost**: ₹15,407.10 (1,540,710 paise)
- **Expected Total Cost (with Collections)**: ₹15,407.10 (1,540,710 paise)
- **NBFC Unsecured Loan Comparison Baseline**: ₹84,128.14 (8,412,814 paise)
- **Calculated Savings vs NBFC Baseline**: ₹68,721.04 (81.7%)

### Table 4.1: Guaranteed Plan (Executed Levers with Binding Cash Delivery)

| Product | Scope | Amount (₹) | Week | Tenor Days | Cost (₹) | Effective Annual Rate | Tier |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TREDS_INVOICE_DISCOUNTING` | Invoice 395 | ₹1,407,657.69 | W1 | 47 | ₹15,407.10 | 8.59% | T3 |

### Table 4.2: Expected Extra from Collections (Uncertain Timing, Not Counted for Guaranteed Validity)

| Product | Scope | Amount (₹) | Week | Tenor Days | Cost (₹) | Effective Annual Rate | Tier |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `COLLECTIONS_PUSH` | Invoice 378 | ₹197,897.00 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 379 | ₹198,442.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 381 | ₹215,531.00 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 383 | ₹368,709.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 384 | ₹195,933.00 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 385 | ₹200,843.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 386 | ₹185,262.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 387 | ₹208,504.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 388 | ₹196,693.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 389 | ₹217,734.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 390 | ₹216,298.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 391 | ₹203,301.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 392 | ₹214,339.00 | W1 | 0 | ₹0.00 | 0.00% | T2 |
| `COLLECTIONS_PUSH` | Invoice 393 | ₹220,824.50 | W1 | 0 | ₹0.00 | 0.00% | T2 |

## 5. Safety vs Cost Curve

Optimization results across standard probability thresholds under `ALL_WEEKS` horizon-wide safety requirement:

| Target Probability | Status | Guaranteed Cost (₹) | Max Horizon Week Probability | Selected Levers |
| :--- | :--- | :--- | :--- | :--- |
| 40% | **VALID** | ₹6,498.67 | 40.00% | TREDS_INVOICE_DISCOUNTING: ₹593,746.02 |
| 30% | **VALID** | ₹10,306.65 | 30.00% | TREDS_INVOICE_DISCOUNTING: ₹941,658.99 |
| 20% | **VALID** | ₹15,407.10 | 20.00% | TREDS_INVOICE_DISCOUNTING: ₹1,407,657.69 |
| 10% | **VALID** | ₹37,120.28 | 10.00% | TREDS_INVOICE_DISCOUNTING: ₹1,164,650.10, BANK_OD_DRAWDOWN: ₹823,715.56 |

## 6. Pre- and Post-Execution Weekly Probabilities

Per-week probability of cash balance falling below the ₹10,00,000 buffer before and after execution:

| Week | Pre-intervention Prob | Post-execution Prob (Guaranteed) | P10 Post Balance (₹) | P50 Post Balance (₹) |
| :--- | :--- | :--- | :--- | :--- |
| W1 | 0.00% | 0.00% | ₹4,286,454.01 | ₹4,728,103.01 |
| W2 | 0.00% | 0.00% | ₹3,839,290.27 | ₹3,878,486.27 |
| W3 | 3.45% | 0.00% | ₹2,725,866.90 | ₹3,119,253.90 |
| W4 | 4.25% | 0.00% | ₹2,661,358.53 | ₹3,398,777.53 |
| W5 | 0.00% | 0.00% | ₹4,157,977.53 | ₹4,157,977.53 |
| W6 | 79.95% | 6.25% | ₹1,263,224.42 | ₹2,024,011.79 |
| W7 | 60.50% | 14.30% | ₹763,286.68 | ₹2,102,615.70 |
| W8 | 41.20% | 20.00% | ₹360,667.23 | ₹2,139,912.22 |
| W9 | 6.10% | 6.20% | ₹1,365,429.39 | ₹3,223,679.35 |
| W10 | 5.20% | 5.20% | ₹1,592,723.84 | ₹3,834,879.54 |
| W11 | 6.95% | 6.95% | ₹1,351,929.41 | ₹3,899,388.86 |
| W12 | 16.30% | 16.50% | ₹343,696.61 | ₹2,978,561.80 |
| W13 | 16.80% | 16.95% | ₹180,864.07 | ₹3,192,652.98 |

## 7. Stage 4 Execution, Ledger Postings & Security Results

- **Reminders Dispatched (Outbox)**: 0 collections reminders queued/sent (zero monetary cash fabricated).
- **Simulated Delivery & Offline Test Substitution**: All collections reminders and OTP challenges use deterministic local simulated outboxes/inboxes. Execution actors, credentials and as-of dates (`2026-10-13`) operate entirely offline without network side-effects.
- **Sandbox Ledger Postings**: 1 posting(s).
  - **TREDS_SETTLEMENT** (SANDBOX): Net cash proceeds of ₹1,392,250.59 posted on `2026-10-16`; receivable reduction ₹1,407,657.69.

### Security Flow Verifications

| Security Test | Tier | Result |
| :--- | :--- | :--- |
| OTP Step-Up Enforcement | `T3` | PASS (Unverified approval rejected with ActionError OTP_REQUIRED; challenge delivered to simulated sandbox inbox and verified) |
| Approval Token Replay (Single-Use) | `T2/T3` | PASS (Single-use token consumed; second consume rejected with ActionError TOKEN_REPLAY, status_code=403) |
| Parameter Tampering Resistance | `T2/T3` | PASS (Modified payload rejected with ActionError PARAMS_TAMPERED, status_code=403) |
| Document-Origin Direct Payment Attack (T4 Blocked) | `T4` | PASS (Policy evaluation DENY: rules=DOCUMENT_PARAMETERS, tier=T4) |
| Tenant Kill Switch (Instant Circuit Breaker) | `T4` | PASS (Policy evaluation DENY with rule: KILL_SWITCH) |

### Security Incident Counters

| Counter | Value | Description |
| :--- | :--- | :--- |
| `blocked_intents` | **2** | Total intents rejected by security policy gates |
| `token_replays` | **1** | Attempts to replay an already-consumed single-use token |
| `injection_detections` | **3** | Poisoned document prompt injection attempts detected |

## 8. Cryptographic Audit Chain

- **Total Audit Log Entries**: 59
- **Hash Chain Verification**: **VALID**
- **Audit Verification Result**: All SHA-256 parent hash links valid; 0 broken or tampered entries.

## 9. MSMED Act 2006 Statutory Terms & ABC Review

- **Statutory Section 15**: Maximum 45-day agreed payment period; 15 days statutory term if no agreement recorded.
- **Statutory Section 16**: Compound interest with monthly rests at 3× RBI bank rate (5.75% × 3 = 17.25% p.a.).

### Reference Test Fixture Verification
- **Principal**: ₹100,000.00 (10,000,000 paise)
- **Accepted**: `2026-01-01`, statutory due date `2026-01-16` (15 days)
- **Calculation Date**: `2026-03-16` (60 days elapsed)
- **Monthly Rests**: 2 rests, 0 stub days
- **Calculated Compound Interest**: ₹2,895.66 (289,566 paise)
- **Exact Match with Code Formula**: ₹2,895.66 (289,566 paise)

### ABC Engineering Open Receivable
- **Invoice 383**: Due date `2026-01-29`
- **As-Of Date**: `2026-10-13`
- **Overdue Status**: Overdue
- **Statutory Terms Status**: Kept in **REVIEW_REQUIRED** (statutory terms must be formally confirmed by buyer before asserting interest claims).

## 10. Stage 5 Add-on Events Effects

- **Baseline Week 1 P50 Closing Balance (Add-ons OFF)**: ₹4,728,103.01
- **Confirmed Sale Add-on (+₹5,00,000.00)** & **Confirmed PO Add-on (-₹2,00,000.00)**
- **Shifted Week 1 P50 Closing Balance (Add-ons ON)**: ₹5,028,103.01
- **Net Forecast Shift**: ₹+300,000.00 (exact match with +₹3,00,000 net operational cash effect)
- **Toggle Fidelity**: Turning add-on events OFF strictly restores the exact baseline forecast with zero residual leakage.

