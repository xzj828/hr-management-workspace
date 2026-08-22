import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api', () => ({ api: vi.fn(), ensureCsrf: vi.fn() }))

import { api, ensureCsrf } from '@/api'
import { useAuthStore } from './auth'

describe('auth store remembered login', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.mockReset()
    ensureCsrf.mockReset()
  })

  it('sends the remember choice with the login request', async () => {
    api.mockResolvedValue({ username: 'hr' })
    const store = useAuthStore()

    await store.login('hr', 'password', true)

    expect(api).toHaveBeenCalledWith('auth/login/', {
      method: 'POST',
      body: JSON.stringify({ username: 'hr', password: 'password', remember: true }),
    })
  })
})
