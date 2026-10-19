/**
 * Plain user-facing labels for Kosh system enums.
 * Preserves raw enum strings in tooltips (title) and API interfaces.
 */

export const formatEnumLabel = (val: string | null | undefined): string => {
  if (!val) return '-'
  switch (val) {
    case 'REVIEW_REQUIRED':
    case 'REVIEW':
      return 'Needs review'
    case 'NOT_MATCHED':
      return 'Not eligible'
    case 'MATCHED':
      return 'Eligible'
    case 'INSUFFICIENT':
      return 'Not enough options'
    case 'STALE':
      return 'Out of date: re-run'
    case 'VALID':
      return 'Valid'
    case 'PROCESSED':
      return 'Processed clean'
    case 'PROPOSED':
      return 'Proposed'
    case 'PENDING':
    case 'PENDING_APPROVAL':
      return 'Pending approval'
    case 'APPROVED':
      return 'Approved'
    case 'REJECTED':
      return 'Rejected'
    case 'EXECUTED':
      return 'Executed'
    case 'EXPIRED':
      return 'Expired'
    case 'BLOCKED':
      return 'Blocked'
    case 'FAILED':
      return 'Failed'
    case 'DISPUTED':
      return 'Disputed'
    case 'OPEN':
      return 'Open'
    case 'PAID':
      return 'Paid'
    case 'PARTIAL':
      return 'Partial'
    case 'OBLIGATION_CLUSTER':
      return 'Payments due together'
    case 'SUPPLIER_PAYMENT':
      return 'Supplier payment'
    case 'COLLECTION_FOLLOWUP':
      return 'Collection follow-up'
    case 'TREDS_INVOICE_DISCOUNTING':
      return 'TReDS invoice discounting'
    case 'CGTMSE_WORKING_CAPITAL':
      return 'CGTMSE credit guarantee'
    case 'GEM_SAHAY_PO_FINANCING':
      return 'GeM Sahay PO financing'
    case 'NBFC_LINE':
      return 'NBFC credit line'
    case 'BANK_STATEMENT':
      return 'Bank statement'
    case 'SALES_INVOICES':
      return 'Sales invoices'
    case 'PURCHASE_BILLS':
      return 'Purchase bills'
    case 'BOOKS_EXPORT':
      return 'Accounting export'
    case 'CRAC_RECEIPT':
      return 'CRAC acceptance'
    default:
      return val.replace(/_/g, ' ')
  }
}
