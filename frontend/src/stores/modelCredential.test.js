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

  it('tests the saved model connection and keeps the latency state', async () => {
    api.mockResolvedValue({ ok: true, model: 'chat', latency_ms: 184, detail: '连接成功' })
    const store = useModelCredentialStore()

    const result = await store.testConnection()

    expect(api).toHaveBeenCalledWith('account/model-credential/test/', { method: 'POST' })
    expect(result.ok).toBe(true)
    expect(store.connection).toEqual({ status: 'success', model: 'chat', latency_ms: 184, detail: '连接成功' })
  })

  it('exposes a safe connection failure message', async () => {
    api.mockRejectedValue(new Error('认证失败，请检查 API Key'))
    const store = useModelCredentialStore()

    await expect(store.testConnection()).rejects.toThrow('认证失败')
    expect(store.connection.status).toBe('error')
    expect(store.connection.detail).not.toContain('sk-')
  })
})
