export const formatPaiseINR = (paise: number | null | undefined): string => {
  if (paise === null || paise === undefined || !Number.isSafeInteger(paise)) return '-'
  const value = BigInt(paise)
  const negative = value < BigInt(0)
  const magnitude = negative ? -value : value
  const rupees = magnitude / BigInt(100)
  const cents = (magnitude % BigInt(100)).toString().padStart(2, '0')
  const grouped = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(rupees)
  return `${negative ? '-' : ''}\u20B9${grouped}.${cents}`
}

/**
 * Parses user input in Indian Rupees into exact integer paise.
 * Preserves strict distinction between blank/omitted (null) and explicit zero (0).
 * Avoids IEEE 754 floating-point inaccuracies by splitting into integer string parts.
 */
export function parseRupeesToPaise(input: string | number | undefined | null): number | null {
  if (input === undefined || input === null) return null
  if (typeof input === 'number') {
    if (!Number.isFinite(input)) return null
    // If already an integer or finite float, convert via fixed string to preserve decimals
    input = input.toFixed(2)
  }
  let str = input.trim()
  if (str === '') return null

  // Handle leading sign
  const isNegative = str.startsWith('-')
  if (isNegative || str.startsWith('+')) {
    str = str.slice(1).trim()
  }

  // Remove leading currency symbols like ₹, Rs, Rs., etc.
  str = str.replace(/^(?:₹|rs\.?|inr)\s*/i, '')
  // Strip thousands commas
  str = str.replace(/,/g, '').trim()
  if (str === '') return null

  // Match optional fractional part (1 or 2 digits, or trailing extra digits)
  const match = /^(\d+)(?:\.(\d+))?$/.exec(str)
  if (!match) return null

  const wholeStr = match[1]
  const fracStr = match[2] || ''

  try {
    const whole = BigInt(wholeStr)
    // Take first 2 fractional digits; if 1 digit, pad with 0; if >2, round or truncate to 2
    let paisePart = 0n
    if (fracStr.length === 1) {
      paisePart = BigInt(fracStr) * 10n
    } else if (fracStr.length >= 2) {
      const firstTwo = fracStr.slice(0, 2)
      // Check 3rd digit for rounding
      const third = fracStr.length > 2 ? parseInt(fracStr[2], 10) : 0
      paisePart = BigInt(firstTwo) + (third >= 5 ? 1n : 0n)
    }

    let total = whole * 100n + paisePart
    if (isNegative) total = -total

    if (total > BigInt(Number.MAX_SAFE_INTEGER) || total < BigInt(Number.MIN_SAFE_INTEGER)) {
      return null
    }
    return Number(total)
  } catch {
    return null
  }
}
