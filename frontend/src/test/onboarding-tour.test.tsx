import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { OnboardingTour, TOUR_STEPS, getTourStorageKey } from '@/features/tour/OnboardingTour'

const mockedNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockedNavigate,
  }
})

describe('OnboardingTour component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('does not render dialog when open is false', () => {
    render(
      <MemoryRouter>
        <OnboardingTour open={false} onClose={vi.fn()} />
      </MemoryRouter>
    )
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('renders step 1 with all key elements when open is true', () => {
    render(
      <MemoryRouter>
        <OnboardingTour open={true} onClose={vi.fn()} />
      </MemoryRouter>
    )

    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(screen.getByText(/Step 1 of 6/i)).toBeInTheDocument()
    expect(screen.getByText(/1\. Connect & Ingest Verifiable Data/i)).toBeInTheDocument()
    expect(screen.getByText(/Tamper-evident invoice & bank intake/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Next/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Back/i })).toBeDisabled()
  })

  it('advances to step 2 when Next button is clicked', () => {
    render(
      <MemoryRouter>
        <OnboardingTour open={true} onClose={vi.fn()} />
      </MemoryRouter>
    )

    const nextBtn = screen.getByRole('button', { name: /Next/i })
    fireEvent.click(nextBtn)

    expect(screen.getByText(/Step 2 of 6/i)).toBeInTheDocument()
    expect(screen.getByText(/2\. Ledger: Verified vs\. Held-For-Review/i)).toBeInTheDocument()
    expect(mockedNavigate).toHaveBeenCalledWith('/ledger')
  })

  it('navigates with ArrowRight and ArrowLeft keyboard shortcuts', () => {
    render(
      <MemoryRouter>
        <OnboardingTour open={true} onClose={vi.fn()} />
      </MemoryRouter>
    )

    // Advance to step 2 with ArrowRight
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByText(/Step 2 of 6/i)).toBeInTheDocument()
    expect(mockedNavigate).toHaveBeenCalledWith('/ledger')

    // Go back to step 1 with ArrowLeft
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(screen.getByText(/Step 1 of 6/i)).toBeInTheDocument()
    expect(mockedNavigate).toHaveBeenCalledWith('/connect')
  })

  it('closes tour on Escape key', () => {
    const handleClose = vi.fn()
    render(
      <MemoryRouter>
        <OnboardingTour open={true} onClose={handleClose} />
      </MemoryRouter>
    )

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(handleClose).toHaveBeenCalledTimes(1)
  })

  it('guards against keystrokes when focused inside form input fields', () => {
    const handleClose = vi.fn()
    render(
      <MemoryRouter>
        <div>
          <input data-testid="user-input" defaultValue="test text" />
          <OnboardingTour open={true} onClose={handleClose} />
        </div>
      </MemoryRouter>
    )

    const input = screen.getByTestId('user-input')
    input.focus()

    // Dispatching ArrowRight while focused in an input should NOT advance step
    fireEvent.keyDown(input, { key: 'ArrowRight' })
    expect(screen.getByText(/Step 1 of 6/i)).toBeInTheDocument()
    expect(mockedNavigate).not.toHaveBeenCalled()

    // Dispatching Escape while typing should NOT close tour
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(handleClose).not.toHaveBeenCalled()
  })

  it('saves versioned completion state in localStorage incorporating user, workspace and tour version', () => {
    const handleClose = vi.fn()
    render(
      <MemoryRouter>
        <OnboardingTour open={true} onClose={handleClose} userId="test_user@example.com" workspaceId={42} />
      </MemoryRouter>
    )

    const skipBtn = screen.getByRole('button', { name: /Skip tour/i })
    fireEvent.click(skipBtn)

    expect(handleClose).toHaveBeenCalledTimes(1)
    const expectedKey = 'kosh_tour_completed_v1_test_user_example_com_ws_42'
    expect(localStorage.getItem(expectedKey)).toBe('true')
  })

  it('restarts to step 1 when restart button is clicked', () => {
    render(
      <MemoryRouter>
        <OnboardingTour open={true} onClose={vi.fn()} />
      </MemoryRouter>
    )

    // Advance to step 2
    fireEvent.click(screen.getByRole('button', { name: /Next/i }))
    expect(screen.getByText(/Step 2 of 6/i)).toBeInTheDocument()

    // Click restart button
    const restartBtn = screen.getByRole('button', { name: /Restart tour from step 1/i })
    fireEvent.click(restartBtn)

    expect(screen.getByText(/Step 1 of 6/i)).toBeInTheDocument()
    expect(mockedNavigate).toHaveBeenCalledWith('/connect')
  })

  it('renders gracefully when targetSelector element does not exist in DOM', () => {
    render(
      <MemoryRouter>
        <OnboardingTour open={true} onClose={vi.fn()} />
      </MemoryRouter>
    )

    // No spotlight outline should be rendered if target element is not found
    expect(screen.queryByTestId('tour-target-spotlight')).toBeNull()
    // Dialog itself is fully intact
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
