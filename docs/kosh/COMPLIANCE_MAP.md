# Kosh Regulatory & Statutory Compliance Map

Detailed statutory matrix mapping Indian financial and data privacy regulations to Kosh technical controls, code implementations, and automated verification tests.

---

## 1. Statutory Compliance Matrix

| Regulation / Statute | Statutory Requirement | Kosh Feature & Control | Implementation (File:Line) | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **MSMED Act 2006, Section 15** | Buyer must make payment to supplier within agreed period not exceeding **45 days** (or **15 days** if no period agreed). | **Collections Push**: Tracks buyer due dates against statutory 45-day ceiling; flags overdue receivables for statutory reminder dispatch. | `app/lending/catalogue.py:35`, `app/finance/collections.py:12` | `tests/test_kosh_stage5_2_collections.py::test_msmed_interest_calculation` |
| **MSMED Act 2006, Section 16** | Mandatory penal compound interest with monthly rests at **three times the RBI bank rate** (5.75% $\times 3 =$ **17.25% p.a.**) from the appointed day. | **MSMED Statutory Interest Calculator**: Computes accrued statutory compound interest with monthly rests for overdue MSME invoices. | `app/finance/collections.py:15-35`, `app/core/config.py:251` | `tests/test_kosh_stage5_2_collections.py::test_msmed_interest_matches_statutory_formula` |
| **Pradhan Mantri Mudra Yojana (PMMY)** | MUDRA loan categories: **Shishu** (up to ₹50,000), **Kishore** (₹50,001 to ₹5,00,000), and **Tarun** (₹5,00,001 to ₹10,00,000 / 100,000,000 paise ceiling). | **MUDRA Eligibility Engine**: Evaluates borrower capital requirements against category caps. Rejects borrowings exceeding the ₹10 Lakh statutory limit. | `app/lending/catalogue.py:55-75`, `app/lending/rules/borrowing.py:20` | `tests/test_kosh_stage2_evaluation.py::test_mudra_loan_eligibility` |
| **TReDS CPSE Mandate (Ministry of MSME)** | Central Public Sector Enterprises (CPSEs) and large corporates (>₹500 Cr turnover) mandated to register on TReDS platforms. | **TReDS Factoring Engine**: Matches open receivables from confirmed CPSE counterparties (e.g. Deccan Heavy Machines Ltd) for institutional discounting. | `app/lending/catalogue.py:20-30`, `app/lending/service.py:90` | `tests/test_kosh_stage2_evaluation.py::test_treds_evaluation_matches_cpse` |
| **Digital Personal Data Protection (DPDP) Act 2023 & Rules 2025** | Prior, informed, purpose-specific affirmative consent; strict purpose limitation; instant consent revocation. | **Granular Consent Service**: Ingestion requires active consent per document kind (`BANK_STATEMENT`, `SALES_INVOICE`). Sharing with external entities requires explicit grant. | `app/consent/service.py:25-50`, `app/consent/sharing.py:15-40` | `tests/test_kosh_stage1_storage.py::test_upload_without_consent_raises_permission_error`, `tests/test_kosh_stage4_intents.py` |
| **RBI Digital Lending Directions 2025** | Unbiased loan comparison; prohibition of paid rankings; explicit borrower consent for third-party data sharing. | **Mathematical Least-Cost Optimizer**: Orders products strictly by effective annual cost per net rupee. Explicit parameter and field binding for data sharing. | `app/finance/plan.py:180`, `app/consent/sharing.py:25` | `tests/test_kosh_stage5_plan.py::test_plan_orders_by_cost_per_net_rupee` |
| **RBI FREE-AI Framework** | Human-in-the-loop oversight; explainability; auditable decision trails; no autonomous execution. | **Safeguarded Action Pipeline**: T3 capital disbursements require dual-control sign-off and OTP step-up. Every forecast, intent, and approval is hash-chained. | `app/actions/approvals.py:55`, `app/actions/step_up.py:20`, `app/audit/ledger.py:15` | `tests/test_kosh_stage4_approvals.py::test_t3_creator_needs_other_approver_when_one_exists`, `tests/test_kosh_stage4_hash_chain.py` |
| **Information Technology Act 2000 & CERT-In** | Preservation of forensic logs; security event tracking; prevention of unauthorized computer tampering. | **Cryptographic Hash Chain**: SHA-256 sequential hash chaining (`KoshAuditEntry`). Tampering with any historical entry invalidates the chain. | `app/audit/verify.py:10-25`, `scripts/verify_audit_chain.py` | `tests/test_kosh_stage4_hash_chain.py::test_tampered_audit_chain_fails_verification` |

---

## 2. Statutory Sources & Reference Links

1. **MSMED Act 2006 (Act No. 27 of 2006)**:
   - *Sections 15 & 16*: Provisions related to delayed payments to Micro and Small Enterprises.
   - Reference: [Ministry of Micro, Small and Medium Enterprises](https://msme.gov.in/).
2. **Pradhan Mantri Mudra Yojana (PMMY)**:
   - *Guidelines on Lending Categories*: Department of Financial Services, Ministry of Finance, Government of India.
   - Reference: [MUDRA Official Portal](https://www.mudra.org.in/).
3. **TReDS Guidelines & CPSE Notifications**:
   - Reserve Bank of India Guidelines on Trade Receivables Discounting System (TReDS) & Ministry of MSME Notification S.O. 5621(E) dated 2nd November 2018.
4. **Digital Personal Data Protection Act 2023 (Act No. 22 of 2023)**:
   - Ministry of Electronics and Information Technology (MeitY), Government of India.
5. **Reserve Bank of India (Digital Lending) Directions 2025**:
   - Department of Regulation, Reserve Bank of India.
