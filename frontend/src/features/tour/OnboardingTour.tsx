import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Compass,
  ChevronRight,
  ChevronLeft,
  X,
  CheckCircle2,
  Sparkles,
  ShieldCheck,
  TrendingUp,
  Layers,
  FileCheck2,
  RotateCcw,
} from 'lucide-react'
import { getSession } from '@/lib/auth'

export interface TourStep {
  id: string
  route: string
  title: string
  subtitle: string
  description: string
  highlights: string[]
  icon: React.ComponentType<{ className?: string }>
  targetSelector: string
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: 'connect',
    route: '/connect',
    title: '1. Connect & Ingest Verifiable Data',
    subtitle: 'Data Integrity & Tamper-Evident Intake',
    description:
      'Integrate ERP accounting records, bank statements, and GeM tender feeds. Every invoice and financial fact is ingested with cryptographic SHA-256 evidence hashes so unverified claims can never be hallucinated.',
    highlights: [
      'Tamper-evident invoice & bank intake',
      'Direct GeM tender opportunity discovery',
      'Zero fabricated or assumed balance data',
    ],
    icon: Compass,
    targetSelector: 'section[aria-label="Connect"]',
  },
  {
    id: 'ledger',
    route: '/ledger',
    title: '2. Ledger: Verified vs. Held-For-Review',
    subtitle: 'Dual-Category Working Capital Tracking',
    description:
      'Inspect verified payables and receivables alongside unverified claims. Kosh strictly isolates held-for-review items into separate categories so that supplier disputes never distort your true operating cash.',
    highlights: [
      'Dual-category accounting isolation',
      'Documented verification status badges',
      'Owner-controlled payable confirmation',
    ],
    icon: FileCheck2,
    targetSelector: 'section[aria-label="Ledger"]',
  },
  {
    id: 'cash',
    route: '/cash',
    title: '3. 13-Week Authoritative Cash Forecast',
    subtitle: 'Probabilistic Monte Carlo Horizon',
    description:
      'Explore probabilistic cash runway modeling over 13 weeks. View median trajectories (P50), conservative downside boundaries (P10), and automated safety buffer shortfall alerts with clear root-cause attribution.',
    highlights: [
      'P10–P90 uncertainty intervals',
      'Safety buffer deficit alerts',
      'Deterministic root-cause attribution',
    ],
    icon: TrendingUp,
    targetSelector: 'section[aria-label="Cash forecast"]',
  },
  {
    id: 'plan',
    route: '/plan',
    title: '4. Financing Criteria & Binding Plan',
    subtitle: 'Statutory Facility Matching & Frozen Hashes',
    description:
      'Evaluate pre-qualification against statutory financing facilities (TReDS, CGTMSE, GeM Sahay, NBFC lines). Generate binding, sha256-signed action plans that automatically invalidate if underlying ledger facts drift.',
    highlights: [
      'Statutory facility qualification scoring',
      'Frozen binding plan hash integrity',
      'Automatic stale-plan recalculation triggers',
    ],
    icon: Layers,
    targetSelector: 'section[aria-label="Financing plan"]',
  },
  {
    id: 'approvals',
    route: '/approvals',
    title: '5. Stage 4 Human Approvals Gate',
    subtitle: 'Four-Eyes Governance & Outbound Pause',
    description:
      'Zero financial dispatches or external messages occur autonomously. All proposed actions pause safely in the Approvals queue waiting for explicit owner four-eyes confirmation before any simulated execution.',
    highlights: [
      'Strict four-eyes human authorization',
      'Sandbox execution and dry-runs',
      'T3 owner OTP governance for high-risk actions',
    ],
    icon: ShieldCheck,
    targetSelector: 'section[aria-label="Approvals"]',
  },
  {
    id: 'audit',
    route: '/audit',
    title: '6. Tamper-Evident SHA-256 Audit Trail',
    subtitle: 'Append-Only Cryptographic Chain',
    description:
      'Inspect the append-only cryptographic audit chain. Every calculation, user decision, policy evaluation, and sandbox dispatch is chained with parent SHA-256 hashes, verifiable and exportable at any time.',
    highlights: [
      'Cryptographic parent-hash chaining',
      'Comprehensive security tier logs (T0–T3)',
      'Instant JSON / CSV export for external auditors',
    ],
    icon: Sparkles,
    targetSelector: 'section[aria-label="Audit"]',
  },
]

export function getTourStorageKey(
  userId?: string | null,
  workspaceId?: string | number | null
): string {
  const session = getSession()
  const user = (userId || session?.email?.trim() || 'demo_user').replace(/[^a-zA-Z0-9_-]/g, '_')
  let ws = workspaceId != null ? String(workspaceId) : ''
  if (!ws) {
    try {
      ws = localStorage.getItem('gem.activeSeller') || 'default_ws'
    } catch {
      ws = 'default_ws'
    }
  }
  const safeWs = ws.replace(/[^a-zA-Z0-9_-]/g, '_')
  return `kosh_tour_completed_v1_${user}_ws_${safeWs}`
}

export function isTourCompleted(
  userId?: string | null,
  workspaceId?: string | number | null
): boolean {
  try {
    return localStorage.getItem(getTourStorageKey(userId, workspaceId)) === 'true'
  } catch {
    return false
  }
}

export function resetTourCompletion(
  userId?: string | null,
  workspaceId?: string | number | null
): void {
  try {
    localStorage.removeItem(getTourStorageKey(userId, workspaceId))
  } catch {
    /* storage unavailable */
  }
}

interface TargetRect {
  top: number
  left: number
  width: number
  height: number
}

interface OnboardingTourProps {
  open: boolean
  onClose: () => void
  userId?: string | null
  workspaceId?: string | number | null
}

export const OnboardingTour: React.FC<OnboardingTourProps> = ({
  open,
  onClose,
  userId,
  workspaceId,
}) => {
  const [currentStepIndex, setCurrentStepIndex] = useState(0)
  const [targetRect, setTargetRect] = useState<TargetRect | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const dialogRef = useRef<HTMLDivElement>(null)
  const nextBtnRef = useRef<HTMLButtonElement>(null)

  const step = TOUR_STEPS[currentStepIndex]

  // Track target element coordinates for spotlight highlight
  const updateTargetRect = useCallback(() => {
    if (!step?.targetSelector) {
      setTargetRect(null)
      return
    }

    try {
      const el = document.querySelector(step.targetSelector)
      if (el && el.getBoundingClientRect) {
        const r = el.getBoundingClientRect()
        // Only set rect if element has positive dimensions
        if (r.width > 0 && r.height > 0) {
          setTargetRect({
            top: r.top + window.scrollY,
            left: r.left + window.scrollX,
            width: r.width,
            height: r.height,
          })
          return
        }
      }
    } catch {
      /* Fallback gracefully */
    }
    setTargetRect(null)
  }, [step])

  // Recalculate spotlight whenever step changes, or on resize / scroll
  useEffect(() => {
    if (!open) {
      setTargetRect(null)
      return
    }

    // Small delay to allow route view transition to settle
    const timer = setTimeout(updateTargetRect, 100)
    window.addEventListener('resize', updateTargetRect)
    window.addEventListener('scroll', updateTargetRect, true)

    return () => {
      clearTimeout(timer)
      window.removeEventListener('resize', updateTargetRect)
      window.removeEventListener('scroll', updateTargetRect, true)
    }
  }, [open, currentStepIndex, location.pathname, updateTargetRect])

  const handleNext = useCallback(() => {
    if (currentStepIndex < TOUR_STEPS.length - 1) {
      const nextIndex = currentStepIndex + 1
      setCurrentStepIndex(nextIndex)
      navigate(TOUR_STEPS[nextIndex].route)
    } else {
      try {
        localStorage.setItem(getTourStorageKey(userId, workspaceId), 'true')
      } catch {
        /* ignore storage error */
      }
      onClose()
    }
  }, [currentStepIndex, navigate, onClose, userId, workspaceId])

  const handlePrev = useCallback(() => {
    if (currentStepIndex > 0) {
      const prevIndex = currentStepIndex - 1
      setCurrentStepIndex(prevIndex)
      navigate(TOUR_STEPS[prevIndex].route)
    }
  }, [currentStepIndex, navigate])

  const handleSkip = useCallback(() => {
    try {
      localStorage.setItem(getTourStorageKey(userId, workspaceId), 'true')
    } catch {
      /* ignore storage error */
    }
    onClose()
  }, [onClose, userId, workspaceId])

  const handleRestart = useCallback(() => {
    setCurrentStepIndex(0)
    navigate(TOUR_STEPS[0].route)
  }, [navigate])

  // Focus trap & safe keyboard controls
  useEffect(() => {
    if (!open) return

    const handleKeyDown = (e: KeyboardEvent) => {
      // Guard: do NOT intercept keystrokes if active element is an input, textarea or select
      const activeTag = (document.activeElement?.tagName || '').toLowerCase()
      if (activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select') {
        return
      }

      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        handleNext()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        handlePrev()
      } else if (e.key === 'Tab') {
        // Focus trap inside dialog
        if (!dialogRef.current) return
        const focusables = dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )
        if (focusables.length === 0) return

        const first = focusables[0]
        const last = focusables[focusables.length - 1]

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault()
            last.focus()
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault()
            first.focus()
          }
        }
      }
      // Note: We deliberately do NOT bind Enter globally.
      // Standard HTML button activation handles Enter when a specific button has focus.
    }

    window.addEventListener('keydown', handleKeyDown)
    // Focus the primary action button after mounting
    const timer = setTimeout(() => {
      nextBtnRef.current?.focus()
    }, 50)

    return () => {
      clearTimeout(timer)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [open, currentStepIndex, handleNext, handlePrev, onClose])

  if (!open || !step) return null

  const StepIcon = step.icon

  return (
    <>
      {/* Target element spotlight outline (if target is resolved on screen) */}
      {targetRect && (
        <div
          data-testid="tour-target-spotlight"
          style={{
            position: 'absolute',
            top: targetRect.top - 6,
            left: targetRect.left - 6,
            width: targetRect.width + 12,
            height: targetRect.height + 12,
          }}
          className="pointer-events-none z-40 rounded-2xl border-2 border-primary-500/80 shadow-[0_0_0_9999px_rgba(15,23,42,0.45)] dark:shadow-[0_0_0_9999px_rgba(0,0,0,0.65)] transition-all duration-300"
          aria-hidden="true"
        />
      )}

      {/* Main Tour Modal Dialog */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-step-title"
        aria-describedby="tour-step-description"
        className={`fixed inset-0 z-50 flex items-center justify-center p-4 ${
          targetRect ? 'bg-transparent' : 'bg-metal-950/60'
        } backdrop-blur-xs motion-reduce:transition-none`}
      >
        <div
          ref={dialogRef}
          className="relative w-full max-w-xl rounded-2xl bg-white dark:bg-metal-900 border border-metal-200 dark:border-metal-800 shadow-2xl p-6 sm:p-7 space-y-6 motion-reduce:transition-none animate-fadeIn"
        >
          {/* Top Bar with Step Counter & Close Button */}
          <div className="flex items-center justify-between pb-3 border-b border-metal-100 dark:border-metal-800">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-primary-50 dark:bg-primary-950/60 text-primary-800 dark:text-primary-300 border border-primary-200 dark:border-primary-800">
                <Compass className="w-3.5 h-3.5 text-primary-600 dark:text-primary-400" />
                Kosh Showcase Tour · Step {currentStepIndex + 1} of {TOUR_STEPS.length}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handleRestart}
                aria-label="Restart tour from step 1"
                title="Restart from beginning"
                className="p-1.5 rounded-lg text-metal-400 hover:text-metal-700 dark:hover:text-metal-200 hover:bg-metal-100 dark:hover:bg-metal-800 transition-colors"
              >
                <RotateCcw className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={handleSkip}
                aria-label="Close tour"
                className="p-1.5 rounded-lg text-metal-400 hover:text-metal-700 dark:hover:text-metal-200 hover:bg-metal-100 dark:hover:bg-metal-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Step Content */}
          <div className="space-y-4">
            <div className="flex items-start gap-3.5">
              <div className="p-3 rounded-xl bg-primary-50 dark:bg-primary-950/70 border border-primary-200 dark:border-primary-800 text-primary-700 dark:text-primary-300 shrink-0">
                <StepIcon className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <h3
                  id="tour-step-title"
                  className="text-lg font-bold text-metal-900 dark:text-white tracking-tight"
                >
                  {step.title}
                </h3>
                <p className="text-xs font-semibold text-primary-700 dark:text-primary-400">
                  {step.subtitle}
                </p>
              </div>
            </div>

            <p
              id="tour-step-description"
              className="text-xs sm:text-sm text-metal-600 dark:text-metal-300 leading-relaxed"
            >
              {step.description}
            </p>

            {/* Highlights checklist */}
            <div className="p-3.5 rounded-xl bg-metal-50 dark:bg-metal-800/40 border border-metal-200/80 dark:border-metal-800 space-y-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-metal-500 dark:text-metal-400 block">
                Key Platform Capabilities:
              </span>
              <ul className="space-y-1.5">
                {step.highlights.map((h, i) => (
                  <li
                    key={i}
                    className="flex items-center gap-2 text-xs font-medium text-metal-800 dark:text-metal-200"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5 text-primary-600 dark:text-primary-400 shrink-0" />
                    <span>{h}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Progress Bar & Navigation Controls */}
          <div className="space-y-4 pt-2">
            {/* Step navigation dots */}
            <div className="flex items-center justify-center gap-2" role="tablist" aria-label="Tour navigation steps">
              {TOUR_STEPS.map((s, index) => (
                <button
                  type="button"
                  key={s.id}
                  onClick={() => {
                    setCurrentStepIndex(index)
                    navigate(s.route)
                  }}
                  role="tab"
                  aria-selected={index === currentStepIndex}
                  aria-label={`Jump to step ${index + 1}: ${s.title}`}
                  className={`h-2 rounded-full transition-all duration-200 ${
                    index === currentStepIndex
                      ? 'w-6 bg-primary-600 dark:bg-primary-500'
                      : 'w-2 bg-metal-200 dark:bg-metal-700 hover:bg-metal-300'
                  }`}
                />
              ))}
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-metal-100 dark:border-metal-800">
              <button
                type="button"
                onClick={handleSkip}
                className="text-xs font-semibold text-metal-500 hover:text-metal-800 dark:text-metal-400 dark:hover:text-metal-200 px-2 py-1.5 rounded transition-colors"
              >
                Skip tour
              </button>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handlePrev}
                  disabled={currentStepIndex === 0}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-metal-200 dark:border-metal-700 text-xs font-semibold text-metal-700 dark:text-metal-200 hover:bg-metal-50 dark:hover:bg-metal-800 disabled:opacity-40 transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                  Back
                </button>

                <button
                  type="button"
                  ref={nextBtnRef}
                  onClick={handleNext}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-xs font-semibold shadow-2xs hover:shadow-xs transition-colors"
                >
                  {currentStepIndex === TOUR_STEPS.length - 1 ? (
                    <>
                      Finish tour
                      <CheckCircle2 className="w-3.5 h-3.5" />
                    </>
                  ) : (
                    <>
                      Next
                      <ChevronRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
export default OnboardingTour
