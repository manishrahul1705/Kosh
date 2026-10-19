# Approval policy

Only trusted server planners create intents from valid, current plan lines.
Requests cannot supply payment parameters or document instructions. Immutable
canonical parameters and provenance are SHA-256 bound; changing either invalidates
approval. Controls and every accepted or blocked operation are audited.

T0 read/analysis and T1 internal drafts are automatic. T2 messages require human
approval. T3 money/data requires approval, OTP and purpose/recipient/field-scoped
active consent for sharing. T4 is always blocked: unknown payees, bank-detail
changes, document-origin action parameters and kill-switch operations.
Policy inspection and owner control endpoints remain available to investigate
and disable a kill switch; the switch applies to business action intents.

Approvals are HMAC-SHA256 signatures of canonical JSON containing intent_id,
params_hash, approver_id, nonce and exp. The nonce is the persisted single-use jti.
Tokens expire after five minutes; unused tokens are revoked on rejection/recheck.
KOSH_APPROVAL_SECRET is required in production; development otherwise generates
a random process-local secret. Tokens and codes are never recorded in audit logs.

Only OWNER/APPROVER may approve. If another active OWNER/APPROVER exists, a T3
intent's creator cannot provide its executable approval; a different approver
must authorize it. A sole owner may approve their own T3 intent after step-up.
Global controls additionally require OWNER membership for every seller, preserving
tenant isolation. Newly allowlisted counterparties, recipients and payees require
24 hours of cool-off. Limits use integer paise; daily reservations use the
Asia/Kolkata business day and approved/executing/succeeded intent amounts.


OTP step-up is simulated and unavailable in production. Six-digit challenges
expire after five minutes and permit at most three verification attempts. Resends
are limited to one per 30 seconds and ten per hour per seller/approver; a locked
challenge cannot be bypassed by resending before its expiry. Challenge storage
contains only keyed hashes. Delivery is encrypted into the local sandbox inbox,
visible only to the intended signed-in OWNER/APPROVER in development. Audit records
contain challenge identifiers and outcomes, never plaintext codes. Production
approval secrets must contain at least 32 bytes. Process-secret rotation invalidates
outstanding development tokens and inbox ciphertext.


Outbound data sharing needs a separate sharing consent artifact with exact purpose,
recipient identifier, allowed field list and future expiry. General document-intake
consent does not authorize lender sharing. The policy rechecks the active scope at
proposal, approval and token consumption; revocation or expiry blocks subsequent
sharing even when an approval token exists. Scope matching is exact for purpose and
recipient, and the requested fields must be a subset of the granted fields. Read
checks never mutate an artifact without an audit event. Grants and revocations are
seller-scoped, human-authorized and audited. Recipients currently use the catalogue's
explicit sandbox identifiers; these are not real lender email addresses.


Sandbox adapters have no external transport. Every execution is keyed by intent ID
and exact parameter hash; retries reuse the same transaction, ledger entries and
outbox record. TReDS simulates upload, illustrative bids, best-bid acceptance and
T+1 business-day settlement of the financed part only. Submission is scheduled one
business day before the approved funding date; the approved maturity determines
cost days. OD posts a labelled draw and a scheduled repayment liability; headroom
is rechecked. Lender submission reports SUBMITTED and does not invent a disbursement.
Messages only write the sandbox outbox, never a customer receipt. Sharing rechecks
and locks its active consent scope and audits the exact artifact used. Failure
injection is OWNER-only and development-only, failing before cash/outbox posting.
Reconciliation compares the ledger to canonical intent-derived expected entries
and flags amount, date, status or parameter-binding mismatches. Balances remain
unknown if no base bank balance evidence exists, even when sandbox deltas are known.


After successful execution, the labelled sandbox overlay enters the actual
same-seed forecast, with separate sandbox inflow/outflow totals. Financed receivables
are reduced only by the financed amount; existing books and bank statements remain
unchanged. The original seed, path count, buffer and as-of date are preserved.
Each execution stores before/after probabilities and its new forecast run. A plan
whose executed cash effects do not meet its chosen target is marked INSUFFICIENT,
with no claim that messaging caused a payment. A previous successful reminder with
no confirmed outcome requires review before another immediate collections lever;
re-evaluation can then select honest financing for the remaining gap. Scenario cash
inputs require signed integer paise and cannot impersonate the sandbox component.

Sandbox business days exclude weekends; no holiday calendar is claimed to be
verified. Funding, maturity and repayment dates remain visible in the proof.


Audit export is scoped to the authorized seller. Other sellers' links appear as
opaque sequence/previous-hash/entry-hash anchors, never their payloads or identity
metadata. Verification compares the export snapshot to the trusted persisted chain;
foreign anchor contents cannot be independently reconstructed without that database.
The authorized verify-export endpoint and verify_audit_chain.py --verify-jsonl
--seller-id provide this check without disclosing foreign records. A local privileged
CLI operator can still export the complete database chain using the existing mode.
Security counters report blocked attempts, failed OTPs, token replays, injection
detections and reconciliation mismatches from the append-only audit events.
