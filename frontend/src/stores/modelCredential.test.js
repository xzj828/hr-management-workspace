import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api', () => ({
  api: vi.fn(),
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

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

  it('loads masked model profiles and derives the active configuration', async () => {
    api.mockResolvedValue({ results: [
      { id: 1, name: '快速模型', api_url: 'https://fast.example/v1', model: 'fast', has_api_key: true, key_last4: '5678', is_active: true },
      { id: 2, name: '深度模型', api_url: 'https://deep.example/v1', model: 'deep', has_api_key: true, key_last4: '9012', is_active: false },
    ] })
    const store = useModelCredentialStore()

    await store.loadProfiles()

    expect(store.activeProfile.name).toBe('快速模型')
    expect(store.config.model).toBe('fast')
    expect(store.profiles[0].api_key).toBeUndefined()
  })

  it('activates a saved profile and updates the compatibility state', async () => {
    const selected = { id: 2, name: '深度模型', api_url: 'https://deep.example/v1', model: 'deep', has_api_key: true, key_last4: '9012', is_active: true }
    api.mockResolvedValue(selected)
    const store = useModelCredentialStore()
    store.profiles = [
      { id: 1, name: '快速模型', model: 'fast', is_active: true },
      { ...selected, is_active: false },
    ]

    await store.activateProfile(2)

    expect(api).toHaveBeenCalledWith('account/model-profiles/2/activate/', { method: 'POST' })
    expect(store.activeProfile.id).toBe(2)
    expect(store.config.model).toBe('deep')
  })

  it('keeps the current profile when activation fails', async () => {
    const rejection = new Error('模型请求不合法')
    rejection.status = 400
    api.mockRejectedValue(rejection)
    const store = useModelCredentialStore()
    store.profiles = [
      { id: 1, name: '模型 A', api_url: 'https://a.example/v1', model: 'a', has_api_key: true, key_last4: '1111', is_active: true },
      { id: 2, name: '模型 B', api_url: 'https://b.example/v1', model: 'b', has_api_key: true, key_last4: '2222', is_active: false },
    ]
    store.syncConfigFromProfiles()

    await expect(store.activateProfile(2)).rejects.toThrow('模型请求不合法')

    expect(store.activeProfile.id).toBe(1)
    expect(store.config.model).toBe('a')
    expect(store.switchingId).toBeNull()
    expect(store.error).toContain('模型请求不合法')
  })

  it('reconciles an activation that committed before its response was lost', async () => {
    const store = useModelCredentialStore()
    store.profiles = [
      { id: 1, name: '模型 A', api_url: 'https://a.example/v1', model: 'a', has_api_key: true, key_last4: '1111', is_active: true },
      { id: 2, name: '模型 B', api_url: 'https://b.example/v1', model: 'b', has_api_key: true, key_last4: '2222', is_active: false },
    ]
    api.mockImplementation((path) => {
      if (path === 'account/model-profiles/2/activate/') return Promise.reject(new TypeError('network disconnected'))
      if (path === 'account/model-profiles/') return Promise.resolve({ results: store.profiles.map((profile) => ({ ...profile, is_active: profile.id === 2 })) })
      return Promise.reject(new Error(`unexpected ${path}`))
    })

    const selected = await store.activateProfile(2)

    expect(selected.id).toBe(2)
    expect(store.activeProfile.id).toBe(2)
    expect(store.config.model).toBe('b')
    expect(store.error).toBe('')
  })

  it('reports a confirmed activation failure after reconciliation', async () => {
    const rejection = new TypeError('network disconnected')
    const store = useModelCredentialStore()
    store.profiles = [
      { id: 1, name: '模型 A', api_url: 'https://a.example/v1', model: 'a', has_api_key: true, key_last4: '1111', is_active: true },
      { id: 2, name: '模型 B', api_url: 'https://b.example/v1', model: 'b', has_api_key: true, key_last4: '2222', is_active: false },
    ]
    api.mockImplementation((path) => {
      if (path === 'account/model-profiles/2/activate/') return Promise.reject(rejection)
      if (path === 'account/model-profiles/') return Promise.resolve({ results: store.profiles })
      return Promise.reject(new Error(`unexpected ${path}`))
    })

    await expect(store.activateProfile(2)).rejects.toBe(rejection)

    expect(store.activeProfile.id).toBe(1)
    expect(store.activeStateUncertain).toBe(false)
    expect(store.error).toContain('network disconnected')
  })

  it('marks the active state uncertain when activation reconciliation also fails', async () => {
    const store = useModelCredentialStore()
    store.profiles = [
      { id: 1, name: '模型 A', api_url: 'https://a.example/v1', model: 'a', has_api_key: true, key_last4: '1111', is_active: true },
      { id: 2, name: '模型 B', api_url: 'https://b.example/v1', model: 'b', has_api_key: true, key_last4: '2222', is_active: false },
    ]
    api.mockRejectedValue(new TypeError('network disconnected'))

    await expect(store.activateProfile(2)).rejects.toThrow('切换结果待确认')

    expect(store.activeStateUncertain).toBe(true)
    expect(store.error).toContain('请刷新模型列表')
  })

  it('does not reconcile an old users activation into a new session', async () => {
    let resolveReconciliation
    const store = useModelCredentialStore()
    store.profiles = [
      { id: 1, name: '模型 A', api_url: 'https://a.example/v1', model: 'a', has_api_key: true, key_last4: '1111', is_active: true },
      { id: 2, name: '模型 B', api_url: 'https://b.example/v1', model: 'b', has_api_key: true, key_last4: '2222', is_active: false },
    ]
    api.mockImplementation((path) => {
      if (path === 'account/model-profiles/2/activate/') return Promise.reject(new TypeError('network disconnected'))
      if (path === 'account/model-profiles/') return new Promise((resolve) => { resolveReconciliation = resolve })
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    const pending = store.activateProfile(2)
    await Promise.resolve()
    await Promise.resolve()

    store.reset()
    resolveReconciliation({ results: [{
      id: 2, name: '模型 B', api_url: 'https://b.example/v1', model: 'b', has_api_key: true, key_last4: '2222', is_active: true,
    }] })
    await expect(pending).rejects.toThrow('network disconnected')

    expect(store.profiles).toEqual([])
    expect(store.error).toBe('')
    expect(store.activeStateUncertain).toBe(false)
  })

  it('reconciles a create-and-activate that committed before response loss', async () => {
    const store = useModelCredentialStore()
    api.mockImplementation((path) => {
      if (path === 'account/model-profiles/' && api.mock.calls.length === 1) return Promise.reject(new TypeError('network disconnected'))
      if (path === 'account/model-profiles/') return Promise.resolve({ results: [{
        id: 9, name: '新模型', api_url: 'https://new.example/v1', model: 'new', has_api_key: true, key_last4: '9999', is_active: true,
      }] })
      return Promise.reject(new Error(`unexpected ${path}`))
    })

    const created = await store.createProfile({
      name: '新模型', api_url: 'https://new.example/v1/', model: 'new', api_key: 'sk-new-9999', make_active: true,
    })

    expect(created.id).toBe(9)
    expect(store.activeProfile.id).toBe(9)
    expect(store.activeStateUncertain).toBe(false)
  })

  it('discards an earlier users in-flight model response after reset', async () => {
    let resolveRequest
    api.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve }))
    const store = useModelCredentialStore()
    const pending = store.loadProfiles()

    store.reset()
    resolveRequest({ results: [{ id: 9, name: '上一账号模型', api_url: 'https://old.example/v1', model: 'old', has_api_key: true, key_last4: '1111', is_active: true }] })
    await pending

    expect(store.profiles).toEqual([])
    expect(store.config.has_api_key).toBe(false)
    expect(store.loading).toBe(false)
  })

  it('does not let an older list response overwrite a successful switch', async () => {
    let resolveList
    api.mockImplementation((path) => {
      if (path === 'account/model-profiles/') return new Promise((resolve) => { resolveList = resolve })
      if (path === 'account/model-profiles/2/activate/') {
        return Promise.resolve({ id: 2, name: '模型 B', api_url: 'https://b.example/v1', model: 'b', has_api_key: true, key_last4: '2222', is_active: true })
      }
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    const store = useModelCredentialStore()
    store.profiles = [
      { id: 1, name: '模型 A', api_url: 'https://a.example/v1', model: 'a', has_api_key: true, key_last4: '1111', is_active: true },
      { id: 2, name: '模型 B', api_url: 'https://b.example/v1', model: 'b', has_api_key: true, key_last4: '2222', is_active: false },
    ]
    const staleLoad = store.loadProfiles()

    await store.activateProfile(2)
    resolveList({ results: [
      { id: 1, name: '模型 A', api_url: 'https://a.example/v1', model: 'a', has_api_key: true, key_last4: '1111', is_active: true },
      { id: 2, name: '模型 B', api_url: 'https://b.example/v1', model: 'b', has_api_key: true, key_last4: '2222', is_active: false },
    ] })
    await staleLoad

    expect(store.activeProfile.id).toBe(2)
    expect(store.config.model).toBe('b')
  })

  it('clears the current account configuration', async () => {
    api.mockResolvedValue(null)
    const store = useModelCredentialStore()
    store.config = { api_url: 'https://models.example/v1', model: 'chat', has_api_key: true, key_last4: '1234' }

    await store.clear()

    expect(api).toHaveBeenCalledWith('account/model-credential/', { method: 'DELETE' })
    expect(store.config.has_api_key).toBe(false)
    expect(store.profiles).toEqual([])
  })

  it('does not let an older profile list overwrite a legacy save', async () => {
    let resolveList
    api.mockImplementation((path) => {
      if (path === 'account/model-profiles/') return new Promise((resolve) => { resolveList = resolve })
      if (path === 'account/model-credential/') {
        return Promise.resolve({ api_url: 'https://saved.example/v1', model: 'saved', has_api_key: true, key_last4: '4321' })
      }
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    const store = useModelCredentialStore()
    const staleLoad = store.loadProfiles()

    await store.save({ api_url: 'https://saved.example/v1', model: 'saved', api_key: 'secret' })
    resolveList({ results: [{ id: 1, name: '旧模型', api_url: 'https://old.example/v1', model: 'old', has_api_key: true, key_last4: '1111', is_active: true }] })
    await staleLoad

    expect(store.config.model).toBe('saved')
    expect(store.profiles).toEqual([])
  })

  it('does not let an older profile list overwrite a legacy clear', async () => {
    let resolveList
    api.mockImplementation((path, options) => {
      if (path === 'account/model-profiles/') return new Promise((resolve) => { resolveList = resolve })
      if (path === 'account/model-credential/' && options?.method === 'DELETE') return Promise.resolve(null)
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    const store = useModelCredentialStore()
    store.profiles = [
      { id: 1, name: '当前模型', api_url: 'https://current.example/v1', model: 'current', has_api_key: true, key_last4: '2222', is_active: true },
      { id: 2, name: '备用模型', api_url: 'https://backup.example/v1', model: 'backup', has_api_key: true, key_last4: '3333', is_active: false },
    ]
    store.syncConfigFromProfiles()
    const staleLoad = store.loadProfiles()

    await store.clear()
    resolveList({ results: [{ id: 1, name: '当前模型', api_url: 'https://current.example/v1', model: 'current', has_api_key: true, key_last4: '2222', is_active: true }] })
    await staleLoad

    expect(store.config.has_api_key).toBe(false)
    expect(store.activeProfile).toBeNull()
    expect(store.profiles.map((profile) => profile.id)).toEqual([2])
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
