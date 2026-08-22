import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api', () => ({ api: vi.fn() }))

import { api } from '@/api'
import { useModelCredentialStore } from './modelCredential'

describe('model credential store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.mockReset()
  })

  it('loads only the masked account configuration', async () => {
    api.mockResolvedValue({ api_url: 'https://models.example/v1', model: 'chat', has_api_key: true, key_last4: '1234' })
    const store = useModelCredentialStore()

    await store.load()

    expect(store.config.key_last4).toBe('1234')
    expect(store.config.api_key).toBeUndefined()
  })

  it('clears the current account configuration', async () => {
    api.mockResolvedValue(null)
    const store = useModelCredentialStore()
    store.config = { api_url: 'https://models.example/v1', model: 'chat', has_api_key: true, key_last4: '1234' }

    await store.clear()

    expect(api).toHaveBeenCalledWith('account/model-credential/', { method: 'DELETE' })
    expect(store.config.has_api_key).toBe(false)
  })
})
