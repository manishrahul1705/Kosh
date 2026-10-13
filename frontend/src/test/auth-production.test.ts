import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules() })

describe('development login build boundary', () => {
  it('cannot activate local passwordless login in a production build', async () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEV_LOGIN', 'true')
    vi.resetModules()
    const auth = await import('../lib/auth')
    expect(auth.DEV_LOGIN).toBe(false)
  })
  it('supports explicitly enabled local login in development', async () => {
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_DEV_LOGIN', 'true')
    vi.resetModules()
    const auth = await import('../lib/auth')
    expect(auth.DEV_LOGIN).toBe(true)
  })
})
