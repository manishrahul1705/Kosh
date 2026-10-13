export const formatPaiseINR = (paise: number | null | undefined): string => {
  if (paise === null || paise === undefined) return '-'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 }).format(paise / 100)
}
