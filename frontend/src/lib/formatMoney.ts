export const formatPaiseINR = (paise: number | null | undefined): string => {
  if (paise === null || paise === undefined || !Number.isSafeInteger(paise)) return '-'
  const value=BigInt(paise)
  const negative=value<BigInt(0)
  const magnitude=negative?-value:value
  const rupees=magnitude/BigInt(100)
  const cents=(magnitude%BigInt(100)).toString().padStart(2,'0')
  const grouped=new Intl.NumberFormat('en-IN',{maximumFractionDigits:0}).format(rupees)
  return `${negative?'-':''}?${grouped}.${cents}`
}
