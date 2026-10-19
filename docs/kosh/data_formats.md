# Kosh private data formats

Private files are stored under `KOSH_PRIVATE_STORAGE_PATH/<seller_id>/<sha256>`. User filenames never form storage paths, files are never served statically, and downloads require seller authorization.

## Books CSV

Required columns are `voucher_type`, `invoice_number`, `invoice_date`, `party_name`, `party_gstin`, and `amount`. `voucher_type` is `Sales` or `Purchase`; dates use `YYYY-MM-DD`. Supply either `due_date` or integer `credit_days`. Optional settlement fields are `paid_date` and `paid_amount`. Money is parsed exactly to integer paise. Invalid or ambiguous rows become `REVIEW` and are not silently discarded.

## Bank statement

JSON contains `account_ref_masked`, `currency` (`INR`), `opening_balance`, and `transactions`. Each transaction has `txn_id`, `date`, `narration`, `amount`, `type` (`CREDIT` or `DEBIT`), and `balance`. CSV uses those transaction fields plus `account_ref_masked`. Only the last four account digits are retained.

## Obligations

Obligations contain `kind`, `label`, integer `amount_paise`, `recurrence`, `next_due_date`, optional `day_of_month`, and `active`. Supported kinds are payroll, rent, EMI, GST, TDS, utility, and other.
