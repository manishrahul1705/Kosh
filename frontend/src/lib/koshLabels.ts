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
    default:
      return val.replace(/_/g, ' ')
  }
}
