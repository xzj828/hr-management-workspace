import { defineStore } from 'pinia'
import { api } from '@/api'

export const useModelCredentialStore = defineStore('modelCredential', {
  state: () => ({
    config: { api_url: '', model: '', has_api_key: false, key_last4: '' },
    loading: false,
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
    },
    async clear() {
      await api('account/model-credential/', { method: 'DELETE' })
      this.config = { api_url: '', model: '', has_api_key: false, key_last4: '' }
    },
  },
})
