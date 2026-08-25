import { defineStore } from 'pinia'
import { api } from '@/api'

export const useModelCredentialStore = defineStore('modelCredential', {
  state: () => ({
    config: { api_url: '', model: '', has_api_key: false, key_last4: '' },
    connection: { status: 'unknown', model: '', latency_ms: null, detail: '' },
    loading: false,
    testing: false,
  }),
  actions: {
    async load() {
      this.loading = true
      try {
        this.config = await api('account/model-credential/')
      } finally {
        this.loading = false
      }
    },
    async save(payload) {
      this.config = await api('account/model-credential/', { method: 'PUT', body: JSON.stringify(payload) })
      this.connection = { status: 'unknown', model: '', latency_ms: null, detail: '' }
    },
    async clear() {
      await api('account/model-credential/', { method: 'DELETE' })
      this.config = { api_url: '', model: '', has_api_key: false, key_last4: '' }
      this.connection = { status: 'unknown', model: '', latency_ms: null, detail: '' }
    },
    async testConnection() {
      this.testing = true
      this.connection = { status: 'testing', model: this.config.model || '', latency_ms: null, detail: '正在验证模型连接…' }
      try {
        const result = await api('account/model-credential/test/', { method: 'POST' })
        this.connection = {
          status: 'success',
          model: result.model || this.config.model || '',
          latency_ms: result.latency_ms ?? null,
          detail: result.detail || '连接成功',
        }
        return result
      } catch (error) {
        this.connection = { status: 'error', model: this.config.model || '', latency_ms: null, detail: error.message || '连接失败' }
        throw error
      } finally {
        this.testing = false
      }
    },
  },
})
